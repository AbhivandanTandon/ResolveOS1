"""Heuristic risk score, used only when the notebook's calibrated LightGBM model (services/ml.py)
is unavailable. Either way the score is one input to the deterministic gate, never an authorization.
"""

import logging
import math

log = logging.getLogger("resolveos.risk")

FEATURES = ["amount_usd_log", "exception_severity", "processor_unconfirmed", "evidence_conflict",
            "evidence_stale", "compliance_hold", "moves_money", "rejections", "processor_final"]

_SEVERITY = {"duplicate_event": 0.1, "issuer_decline": 0.1, "returned_transfer": 0.35, "chargeback_no_order": 0.4,
             "stale_evidence": 0.5, "missed_cutoff": 0.55, "network_timeout": 0.6, "conflicting_state": 0.7,
             "compliance_hold": 1.0}
_FX = {"USD": 1.0, "EUR": 1.08, "GBP": 1.27, "INR": 0.012}

def features(*, amount_minor: int, currency: str, exception_type: str, processor_status: str | None,
             conflict: bool, stale: bool, compliance_hold: bool, moves_money: bool, rejections: int) -> dict:
    usd = amount_minor / 100 * _FX.get(currency, 1.0)
    return {
        "amount_usd_log": math.log10(max(usd, 1)),
        "exception_severity": _SEVERITY.get(exception_type, 0.5),
        "processor_unconfirmed": float(processor_status in (None, "pending", "unknown")),
        "evidence_conflict": float(conflict),
        "evidence_stale": float(stale),
        "compliance_hold": float(compliance_hold),
        "moves_money": float(moves_money),
        "rejections": float(rejections),
        "processor_final": float(processor_status in ("captured", "settled", "failed", "declined", "returned")),
    }


def score(f: dict) -> tuple[int, str]:
    """Return (score 0-100, scorer name)."""
    # Amount matters less when no money moves; a final processor status removes most uncertainty.
    s = (
        8 * f["amount_usd_log"] * (0.5 + 0.5 * f["moves_money"])
        + 30 * f["exception_severity"]
        + 14 * f["processor_unconfirmed"] * f["moves_money"]
        + 12 * f["evidence_conflict"]
        + 8 * f["evidence_stale"]
        + 60 * f["compliance_hold"]
        + 10 * f["moves_money"]
        + 3 * f["rejections"]
        - 20 * f["processor_final"] * (1 - f["moves_money"])
    )
    return max(1, min(99, int(round(s)))), "heuristic-v1"


def level(score_: int | None) -> str:
    if score_ is None:
        return "unknown"
    return "low" if score_ < 35 else "medium" if score_ < 75 else "high"
