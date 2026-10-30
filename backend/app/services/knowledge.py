"""Knowledge retrieval.

Two sources, fused by reciprocal rank:
- the notebook's knowledge base (ml_artifacts/resolveos_kb.pkl): hybrid BGE + TF-IDF retrieval over
  policies, playbooks, runbooks, error codes and verified past cases (Wikipedia only on request);
- ResolveOS's own documents in the database (seeded policies, merchant uploads, documents added in the
  UI), searched with BM25.
Retrieved text is always treated as untrusted input and scanned for prompt-injection patterns.
"""

import json
import logging
import math
import re
from collections import Counter
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import KnowledgeChunk
from . import ml

log = logging.getLogger("resolveos.knowledge")
DATA = Path(__file__).resolve().parents[2] / "data" / "knowledge.json"
_TOKEN = re.compile(r"[a-z0-9]+")

INJECTION_PATTERNS = [
    re.compile(p, re.I)
    for p in [
        r"ignore (all )?(previous|prior|above) instructions",
        r"disregard (the )?(system|previous)",
        r"you are now",
        r"(mark|set) the (safety )?gate",
        r"approve (all|every|retries) ",
        r"\bsystem prompt\b",
        r"new idempotency key",
        r"</?(system|assistant|instructions?)>",
    ]
]


def scan_for_injection(text: str) -> list[str]:
    return [p.pattern for p in INJECTION_PATTERNS if p.search(text or "")]


def sanitize_untrusted(text: str, limit: int = 1200) -> str:
    """Neutralise markup that could break out of the data envelope in a prompt."""
    t = (text or "")[:limit]
    t = t.replace("<", "‹").replace(">", "›")
    return t


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def seed_knowledge(db: Session) -> int:
    docs = json.loads(DATA.read_text(encoding="utf-8"))
    existing = set(db.scalars(select(KnowledgeChunk.doc_id)))
    n = 0
    for d in docs:
        if d["doc_id"] in existing:
            continue
        db.add(KnowledgeChunk(doc_id=d["doc_id"], type=d["type"], title=d["title"], body=d["body"],
                              source=d["source"], tags=d.get("tags", []), trusted=d.get("trusted", True)))
        n += 1
    return n


KB_SOURCES = {"policy", "playbook", "runbook", "error_code", "past_case", "wikipedia", "public_doc"}


def search(db: Session, query: str, k: int = 5, doc_type: str | None = None, include_untrusted: bool = True,
           include_background: bool = False, exc_type: str | None = None) -> list[dict]:
    """Search both sources. `exc_type` is a ResolveOS exception type, used to filter the notebook KB."""
    local = _search_local(db, query, k, doc_type, include_untrusted)
    rt = ml.runtime
    if not rt.ready or not query.strip() or (doc_type and doc_type not in KB_SOURCES):
        return local
    try:
        kb = rt.retrieve(query, k=k, exc_type=exc_type and ml.EXC_TO_NB.get(exc_type),
                         include_background=include_background or doc_type in ("wikipedia", "public_doc"),
                         sources=[doc_type] if doc_type else None)
    except Exception as e:  # never let retrieval failures break an investigation
        log.warning("KB retrieval failed, using local BM25 only: %s", e)
        return local
    for h in kb:
        h["security_flags"] = scan_for_injection(h["body"])
    fused: dict[str, tuple[float, dict]] = {}
    for results in (kb, local):
        for rank, h in enumerate(results):
            prev = fused.get(h["doc_id"], (0.0, h))
            fused[h["doc_id"]] = (prev[0] + 1 / (60 + rank + 1), h)
    return [h for _, h in sorted(fused.values(), key=lambda t: t[0], reverse=True)][:k]


def _search_local(db: Session, query: str, k: int, doc_type: str | None, include_untrusted: bool) -> list[dict]:
    chunks = list(db.scalars(select(KnowledgeChunk)))
    if doc_type:
        chunks = [c for c in chunks if c.type == doc_type]
    if not include_untrusted:
        chunks = [c for c in chunks if c.trusted]
    if not chunks:
        return []
    docs = [_tokens(f"{c.title} {c.title} {' '.join(c.tags)} {c.body}") for c in chunks]
    q = _tokens(query)
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / n
    df = Counter(t for d in docs for t in set(d))
    k1, b = 1.4, 0.75
    raw = []
    for c, d in zip(chunks, docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avgdl))
        raw.append(s)
    top = max(raw) or 1.0
    results = []
    for c, s in zip(chunks, raw):
        score = s / top
        if q and score <= 0:
            continue
        flags = scan_for_injection(c.body)
        results.append({
            "doc_id": c.doc_id, "type": c.type, "title": c.title, "body": c.body, "source": c.source,
            "trusted": c.trusted, "tags": c.tags, "score": round(score, 2) if q else None,
            "retrieval": "bm25",
            "security_flags": flags,
        })
    results.sort(key=lambda r: r["score"] or 0, reverse=True)  # an empty query has no scores
    return results[:k]
