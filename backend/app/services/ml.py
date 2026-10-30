"""Runtime for the ResolveOS ML/RAG notebook export (backend/ml_artifacts).

Provides hybrid RAG retrieval, ML triage, an action predictor and a calibrated LightGBM risk model.
None of these can authorize anything: they feed the diagnosis and the risk score, and the
deterministic safety gate still decides.

The notebook uses its own vocabulary (exception types, processor states, rails, action labels);
the maps below translate between it and ResolveOS. Where ResolveOS has no value for a feature, the
training-set median for that exception type is used, and the substitution is recorded in `defaults_used`.
"""

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from ..config import settings

log = logging.getLogger("resolveos.ml")

# ---------------------------------------------------------------- vocabulary maps

EXC_TO_NB = {
    "network_timeout": "NETWORK_TIMEOUT", "duplicate_event": "DUPLICATE_SUBMISSION",
    "compliance_hold": "COMPLIANCE_HOLD", "missed_cutoff": "CUTOFF_MISSED",
    "returned_transfer": "INVALID_BENEFICIARY", "issuer_decline": "INSUFFICIENT_FUNDS",
    "conflicting_state": "LEDGER_MISMATCH", "stale_evidence": "LEDGER_MISMATCH",
}
NB_TO_EXC = {"NETWORK_TIMEOUT": "network_timeout", "DUPLICATE_SUBMISSION": "duplicate_event",
             "COMPLIANCE_HOLD": "compliance_hold", "CUTOFF_MISSED": "missed_cutoff",
             "INVALID_BENEFICIARY": "returned_transfer", "INSUFFICIENT_FUNDS": "issuer_decline",
             "LEDGER_MISMATCH": "conflicting_state", "LATE_SUCCESS_EVENT": "network_timeout"}

LEDGER_TO_NB = {"none": "NOT_POSTED", "not_settled": "PENDING", "captured": "POSTED", "settled": "POSTED",
                "debited": "POSTED"}

# Our action -> the notebook's action label (used as the risk model's `true_action` input).
ACTION_TO_NB = {
    "RETRY_CAPTURE": "SAFE_RETRY", "RECONCILE_WITH_PROCESSOR": "RECONCILE_FIRST",
    "REFRESH_EVIDENCE": "RECONCILE_FIRST", "DROP_DUPLICATE_EVENT": "BLOCK_DUPLICATE",
    "RESUBMIT_NEXT_WINDOW": "DEFER_NEXT_WINDOW", "CORRECT_AND_RESUBMIT": "REQUEST_CORRECTION",
    "REQUEST_MERCHANT_INFO": "REQUEST_CORRECTION", "NOTIFY_CUSTOMER": "DEFER_AND_NOTIFY",
    "ESCALATE_TO_OWNER": "ESCALATE_HUMAN", "ESCALATE_TO_COMPLIANCE": "ESCALATE_COMPLIANCE",
    "ADD_CASE_NOTE": "ESCALATE_HUMAN", "RELEASE_HOLD": "SAFE_RETRY", "REFUND": "SAFE_RETRY",
}
# The notebook's predicted action -> the ResolveOS actions that implement it.
NB_TO_ACTIONS = {
    "SAFE_RETRY": ["RETRY_CAPTURE"], "RECONCILE_FIRST": ["RECONCILE_WITH_PROCESSOR", "REFRESH_EVIDENCE"],
    "CANCEL_PENDING_AND_VERIFY": ["RECONCILE_WITH_PROCESSOR"], "BLOCK_DUPLICATE": ["DROP_DUPLICATE_EVENT"],
    "DEFER_NEXT_WINDOW": ["RESUBMIT_NEXT_WINDOW"], "REQUEST_CORRECTION": ["REQUEST_MERCHANT_INFO", "CORRECT_AND_RESUBMIT"],
    "DEFER_AND_NOTIFY": ["NOTIFY_CUSTOMER"], "ESCALATE_HUMAN": ["ESCALATE_TO_OWNER"],
    "ESCALATE_COMPLIANCE": ["ESCALATE_TO_COMPLIANCE"],
}


def nb_action(action_type: str, exc_nb: str | None) -> str:
    """The notebook label for one of our actions. After a late success, reconciling *is* "cancel the pending
    action and verify": the stale retry has already been invalidated and the result is re-read."""
    if action_type == "RECONCILE_WITH_PROCESSOR" and exc_nb == "LATE_SUCCESS_EVENT":
        return "CANCEL_PENDING_AND_VERIFY"
    return ACTION_TO_NB.get(action_type, "ESCALATE_HUMAN")


def nb_exception(exception_type: str, processor_status: str | None) -> str | None:
    if exception_type == "network_timeout" and processor_status in ("captured", "settled"):
        return "LATE_SUCCESS_EVENT"
    return EXC_TO_NB.get(exception_type)


def nb_processor_status(exception_type: str, status: str | None) -> str:
    if status == "pending":
        return "NO_ACK" if exception_type == "network_timeout" else "PENDING"
    if status in ("captured", "settled", "scheduled", "chargeback"):
        return "SUCCESS"
    if status == "held":
        return "HELD"
    if status == "failed" and exception_type == "missed_cutoff":
        return "REJECTED_CUTOFF"
    if status in ("failed", "declined", "returned"):
        return "FAILED"
    return "UNKNOWN"


def nb_ledger_status(exception_type: str, status: str | None) -> str:
    if exception_type == "compliance_hold":
        return "PENDING"  # held payments are reserved, not posted
    return LEDGER_TO_NB.get(status or "", "NOT_POSTED")


def nb_rail(processor: str, currency: str) -> str:
    if processor.startswith("Processor A"):
        return "CARD"
    if processor.startswith("Processor B"):
        return "SWIFT"
    return {"INR": "NEFT", "EUR": "SEPA"}.get(currency, "ACH")


# ---------------------------------------------------------------- runtime

class MLRuntime:
    def __init__(self):
        self._lock = threading.Lock()
        self.loaded = False
        self.error: str | None = None
        self.kb = None
        self.triage = None
        self.action = None
        self.risk = None
        self.metrics: dict = {}
        self.rail_median: dict[str, float] = {}
        self.exc_median: dict[str, dict] = {}
        self.load_seconds: float | None = None
        self._encoder = None

    @property
    def dir(self) -> Path:
        return Path(settings.ml_artifacts_dir)

    @property
    def ready(self) -> bool:
        return self.loaded and self.error is None

    def load(self) -> bool:
        """Load every artifact once. Failures are recorded and the app keeps its fallbacks."""
        with self._lock:
            if self.loaded:
                return self.ready
            t0 = time.time()
            try:
                if not settings.ml_enabled:
                    raise RuntimeError("ML disabled (ML_ENABLED=false)")
                if not (self.dir / "resolveos_kb.pkl").exists():
                    raise RuntimeError(f"no artifacts in {self.dir}")
                import joblib
                import pandas as pd
                from sentence_transformers import SentenceTransformer

                from .kb_retriever import KnowledgeBase

                self.triage = joblib.load(self.dir / "triage_model.joblib")
                self.action = joblib.load(self.dir / "action_model.joblib")
                self.risk = joblib.load(self.dir / "risk_model.joblib")
                backend = self.triage.get("embed_backend", "st:BAAI/bge-small-en-v1.5")
                if not backend.startswith("st:"):
                    raise RuntimeError(f"unsupported embedding backend {backend}")
                self._encoder = SentenceTransformer(backend[3:], device="cpu")
                self.kb = KnowledgeBase(self.dir / "resolveos_kb.pkl", embed_fn=self._embed)
                if self.kb.backend != backend:
                    raise RuntimeError(f"KB embedded with {self.kb.backend}, triage with {backend}")
                cases = pd.read_parquet(self.dir / "cases.parquet")
                self.rail_median = cases.groupby("rail").amount.median().to_dict()
                cols = ["balance_ratio", "minutes_to_cutoff", "validation_errors", "dup_match", "event_conflict",
                        "pending_action", "evidence_age_min"]
                self.exc_median = cases.groupby("exc_type")[cols].median().to_dict("index")
                mpath = self.dir / "metrics.json"
                self.metrics = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else {}
                self.load_seconds = round(time.time() - t0, 1)
                log.info("ML artifacts loaded in %.1fs: %d KB chunks", self.load_seconds, len(self.kb.chunks))
            except Exception as e:
                self.error = str(e)
                log.warning("ML artifacts unavailable, using fallbacks: %s", e)
            self.loaded = True
            return self.ready

    def _embed(self, texts: list[str]):
        return self._encoder.encode(texts, normalize_embeddings=True, convert_to_numpy=True).astype("float32")

    def status(self) -> dict:
        return {
            "ready": self.ready, "error": self.error, "dir": str(self.dir), "load_seconds": self.load_seconds,
            "kb_chunks": len(self.kb.chunks) if self.kb else 0,
            "embed_backend": self.kb.backend if self.kb else None,
            "invariants": self.kb.meta.get("invariants") if self.kb else None,
        }

    # ---- retrieval

    def retrieve(self, query: str, k: int = 6, exc_type: str | None = None, include_background: bool = False,
                 sources: list[str] | None = None) -> list[dict]:
        hits = self.kb.search(query, k=k, exc_type=exc_type, include_background=include_background,
                              allowed_sources=sources)
        top = 2.0 / 61  # best possible RRF score (rank 1 in both lists) for rrf_k=60
        out = []
        for h in hits:
            src = h.get("source", "unknown")
            text = str(h.get("text", ""))
            title = h.get("source_title")
            if not title or title == "None":
                title = text.split(":", 1)[0] if src in ("error_code", "policy", "playbook") else text.split(" / ")[0]
                if src == "past_case":
                    title = f"Past case {h.get('case_id')} · {h.get('exc_type')} → {h.get('action')}"
            url = h.get("source_url")
            out.append({
                "doc_id": f"KB-{src}-{h.get('id')}", "type": src, "title": title[:160], "body": text,
                "source": h.get("source_tier", src), "source_url": url if url and url != "None" else None,
                "trusted": src in ("policy", "playbook", "runbook", "error_code", "past_case"),
                "tags": [t for t in (h.get("exc_type"), h.get("rail")) if t and t != "None"],
                "score": round(min(1.0, h["rrf_score"] / top), 3), "retrieval": "hybrid",
                "dense_score": round(h["dense_score"], 3), "lexical_score": round(h["lexical_score"], 3),
                "source_tier": h.get("source_tier"),
            })
        return out

    # ---- triage

    def classify(self, text: str) -> dict:
        x = self._embed([text])  # the triage model was trained on unprefixed passage embeddings
        m = self.triage["model"]
        proba = m.predict_proba(x)[0]
        order = proba.argsort()[::-1][:3]
        classes = [str(c) for c in m.classes_]
        top = [{"label": classes[i], "p": round(float(proba[i]), 3)} for i in order]
        return {"label": top[0]["label"], "p": top[0]["p"], "top": top,
                "mapped": NB_TO_EXC.get(top[0]["label"])}

    # ---- tabular models

    def features(self, *, exception_type: str, processor: str, currency: str, amount_minor: int,
                 processor_status: str | None, ledger_status: str | None, retries_used: int, evidence_age_min: float,
                 hold: bool, conflict: bool, idempotency_ok: bool, pending_action: bool,
                 created_at: datetime, tier: str) -> tuple[dict, list[str]]:
        exc_nb = nb_exception(exception_type, processor_status)
        med = self.exc_median.get(exc_nb or "", {})
        defaults_used = []

        def default(name, fallback):
            defaults_used.append(name)
            return float(med.get(name, fallback))

        rail = nb_rail(processor, currency)
        amount = amount_minor / 100
        f = {
            "amount": amount,
            "hour": created_at.hour,
            "retry_count": retries_used,
            "evidence_age_min": round(evidence_age_min, 1),
            "balance_ratio": default("balance_ratio", 9.0),
            "dup_match": int(exception_type == "duplicate_event"),
            "hold_flag": int(hold),
            "minutes_to_cutoff": -7.0 if exception_type == "missed_cutoff" else default("minutes_to_cutoff", 284.0),
            "validation_errors": 1 if exception_type == "returned_transfer" else 0,
            "pending_action": int(pending_action),
            "event_conflict": int(conflict),
            "idempotency_ok": int(idempotency_ok),
            "amount_rel": amount / self.rail_median.get(rail, amount or 1.0),
            "rail": rail,
            "customer_tier": tier,
            "processor_status": nb_processor_status(exception_type, processor_status),
            "ledger_status": nb_ledger_status(exception_type, ledger_status),
        }
        return f, defaults_used

    def _frame(self, f: dict, bundle: dict, action_label: str | None = None):
        import pandas as pd

        row = dict(f)
        if action_label is not None:
            row["true_action"] = action_label
        cols = list(bundle["model"].feature_name_)
        df = pd.DataFrame([{c: row[c] for c in cols}])
        for c, cats in bundle["cat"].items():
            if c in df:
                df[c] = pd.Categorical(df[c], categories=cats)
        return df

    def predict_action(self, f: dict) -> dict:
        b = self.action
        proba = b["model"].predict_proba(self._frame(f, b))[0]
        order = proba.argsort()[::-1][:3]
        top = [{"label": b["actions"][i], "p": round(float(proba[i]), 3),
                "actions": NB_TO_ACTIONS.get(b["actions"][i], [])} for i in order]
        return {"label": top[0]["label"], "p": top[0]["p"], "top": top, "actions": top[0]["actions"]}

    def risk_probability(self, f: dict, action_label: str) -> float:
        b = self.risk
        raw = b["model"].predict_proba(self._frame(f, b, action_label))[:, 1]
        cal = b.get("calibrator")
        return float(cal.predict(raw)[0]) if cal is not None else float(raw[0])

    @property
    def risk_thresholds(self) -> tuple[float, float]:
        return tuple(self.risk.get("thresholds", (0.2, 0.5))) if self.risk else (0.2, 0.5)


def probability_to_score(p: float, thresholds: tuple[float, float]) -> int:
    """Map a calibrated probability onto the 0-100 scale so the model's low/medium/high cut-offs land on
    ResolveOS's 35/75 boundaries. The raw probability is stored alongside the score."""
    lo, hi = thresholds
    if p < lo:
        s = p / lo * 35
    elif p < hi:
        s = 35 + (p - lo) / (hi - lo) * 40
    else:
        s = 75 + (p - hi) / (1 - hi) * 24
    return max(1, min(99, int(round(s))))


runtime = MLRuntime()
