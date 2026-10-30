"""Hybrid retriever from the ResolveOS ML notebook export (resolveos_retriever.py), vendored after review.

Dense BGE scores and TF-IDF lexical scores are fused with reciprocal-rank fusion. Operational search
excludes Wikipedia, raw customer messages and unverified pages unless background sources are requested.
Changes from the export: the embedder is injected so it can be shared with the triage model.
Only load pickle files you created yourself: pickle can execute code.
"""

import pickle

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

OPERATIONAL_SOURCES = {"policy", "playbook", "runbook", "error_code", "past_case"}
BACKGROUND_SOURCES = {"wikipedia", "public_doc"}


class KnowledgeBase:
    def __init__(self, path, embed_fn=None):
        with open(path, "rb") as f:
            d = pickle.load(f)
        self.meta = {k: v for k, v in d.items() if k not in ("chunks", "embeddings")}
        self.chunks = d["chunks"]
        self.E = np.asarray(d["embeddings"], dtype="float32")
        self.backend = d["embed_backend"]
        self.prefix = d.get("query_prefix", "")
        self.sources = np.array([c.get("source", "unknown") for c in self.chunks])
        self.exc = np.array([c.get("exc_type") or "" for c in self.chunks])
        self.texts = [str(c.get("text", "")) for c in self.chunks]
        self.lexical = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, max_features=200000)
        self.X_lex = self.lexical.fit_transform(self.texts) if self.texts else None
        self._embed = embed_fn  # callable(list[str]) -> np.ndarray of normalised query vectors

    def search_batch(self, queries, k=6, source=None, exc_type=None, min_score=-1.0,
                     include_background=False, allowed_sources=None, rrf_k=60):
        if self._embed is None:
            raise RuntimeError("no embedder configured")
        queries = list(queries)
        Q = self._embed([self.prefix + q for q in queries])
        if allowed_sources is not None:
            allowed = set([allowed_sources] if isinstance(allowed_sources, str) else allowed_sources)
        elif source is not None:
            allowed = set([source] if isinstance(source, str) else source)
        else:
            allowed = set(OPERATIONAL_SOURCES)
            if include_background:
                allowed |= BACKGROUND_SOURCES
        mask = np.isin(self.sources, list(allowed))
        if exc_type:
            # Global policies apply to every case; other exception-specific chunks must match.
            mask &= (self.exc == exc_type) | (self.sources == "policy")
        idx = np.flatnonzero(mask)
        if len(idx) == 0:
            return [[] for _ in queries]

        Xq = self.lexical.transform(queries)
        out = []
        candidate_n = min(len(idx), max(k * 10, 50))
        for qi, q in enumerate(Q):
            dense_scores = self.E[idx] @ q
            lex_scores = (self.X_lex[idx] @ Xq[qi].T).toarray().ravel()
            dense_order = np.argsort(-dense_scores)[:candidate_n]
            lex_order = np.argsort(-lex_scores)[:candidate_n]
            dense_rank = {int(idx[pos]): rank + 1 for rank, pos in enumerate(dense_order)}
            lex_rank = {int(idx[pos]): rank + 1 for rank, pos in enumerate(lex_order)}
            candidates = set(dense_rank) | set(lex_rank)
            hits = []
            for original_idx in candidates:
                local_pos = int(np.searchsorted(idx, original_idx))
                ds = float(dense_scores[local_pos])
                ls = float(lex_scores[local_pos])
                if ds < min_score:
                    continue
                rrf = (1.0 / (rrf_k + dense_rank[original_idx]) if original_idx in dense_rank else 0.0) + \
                      (1.0 / (rrf_k + lex_rank[original_idx]) if original_idx in lex_rank else 0.0)
                chunk = dict(self.chunks[original_idx])
                hits.append(dict(score=rrf, rrf_score=rrf, dense_score=ds, lexical_score=ls,
                                 source_url=chunk.get("source_url"), source_title=chunk.get("source_title"),
                                 **{key: value for key, value in chunk.items()
                                    if key not in ("source_url", "source_title")}))
            hits.sort(key=lambda h: h["rrf_score"], reverse=True)
            out.append(hits[:k])
        return out

    def search(self, query, **kw):
        return self.search_batch([query], **kw)[0]
