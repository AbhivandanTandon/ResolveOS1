"""Simulated payment processor and ledger.

Everything here is synthetic. The processor keeps idempotency results so a retry that reuses a key
returns the original outcome instead of charging again, exactly like a well-behaved real processor.
"""

from datetime import timedelta

from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import SimPayment


class ProcessorError(Exception):
    pass


def read_processor(db: Session, payment_id: str) -> dict:
    p = db.get(SimPayment, payment_id)
    if p is None:
        raise ProcessorError(f"unknown payment {payment_id}")
    now = utcnow()
    if p.processor_feed_lag_s:
        as_of = now - timedelta(seconds=p.processor_feed_lag_s)
    else:
        as_of = now
        p.processor_as_of = now
    return {
        "payment_id": p.id,
        "processor": p.processor,
        "status": p.processor_status,
        "as_of": as_of,
        "captures": len(p.captures),
        "compliance_hold": p.compliance_hold,
        "simulated": True,
    }


def read_ledger(db: Session, payment_id: str) -> dict:
    p = db.get(SimPayment, payment_id)
    if p is None:
        raise ProcessorError(f"unknown payment {payment_id}")
    return {"payment_id": p.id, "status": p.ledger_status, "entries": list(p.ledger_entries), "as_of": utcnow(),
            "simulated": True}


def _ledger_add(p: SimPayment, kind: str, note: str):
    p.ledger_entries = [*p.ledger_entries, {"kind": kind, "amount_minor": p.amount_minor, "currency": p.currency,
                                            "at": utcnow().isoformat() + "Z", "note": note}]


def capture(db: Session, payment_id: str, idempotency_key: str) -> dict:
    p = db.get(SimPayment, payment_id)
    if p.compliance_hold:
        raise ProcessorError("payment is on compliance hold")
    if idempotency_key in p.idempotency_results:
        return {**p.idempotency_results[idempotency_key], "replayed": True}
    p.retries_used += 1
    if p.processor_status == "captured":
        # A new key on an already-captured payment is a genuine second charge. The gate prevents this path.
        p.captures = [*p.captures, {"key": idempotency_key, "at": utcnow().isoformat() + "Z"}]
        result = {"outcome": "captured_again", "duplicate_charge": True}
    else:
        p.processor_status = "captured"
        p.captures = [*p.captures, {"key": idempotency_key, "at": utcnow().isoformat() + "Z"}]
        result = {"outcome": "captured", "duplicate_charge": False}
    p.ledger_status = "captured"
    _ledger_add(p, "capture", f"capture via key {idempotency_key}")
    p.idempotency_results = {**p.idempotency_results, idempotency_key: result}
    return result


def reconcile(db: Session, payment_id: str) -> dict:
    """Bring the ledger in line with the processor's final status. Never moves money."""
    p = db.get(SimPayment, payment_id)
    status = p.processor_status
    if status in ("captured", "settled") and p.ledger_status != status:
        p.ledger_status = status
        _ledger_add(p, status, "recorded from processor reconciliation")
        return {"outcome": "ledger_updated", "processor_status": status}
    if status in ("failed", "declined") and p.ledger_status not in ("none",):
        p.ledger_status = "none"
        _ledger_add(p, "reversal", "reversed after processor reported failure")
        return {"outcome": "ledger_reversed", "processor_status": status}
    if status == "pending":
        return {"outcome": "still_pending", "processor_status": status}
    return {"outcome": "already_consistent", "processor_status": status}


def refresh_feed(db: Session, payment_id: str) -> dict:
    """Ask the processor for a live status instead of the cached settlement feed."""
    p = db.get(SimPayment, payment_id)
    p.processor_feed_lag_s = 0
    truth = p.meta.get("live_status")
    if truth:
        p.processor_status = truth
    return {"outcome": "refreshed", "processor_status": p.processor_status}


def resubmit(db: Session, payment_id: str, idempotency_key: str, note: str) -> dict:
    p = db.get(SimPayment, payment_id)
    if idempotency_key in p.idempotency_results:
        return {**p.idempotency_results[idempotency_key], "replayed": True}
    p.processor_status = "scheduled"
    p.ledger_status = "debited"
    _ledger_add(p, "transfer", note)
    result = {"outcome": "scheduled", "note": note}
    p.idempotency_results = {**p.idempotency_results, idempotency_key: result}
    return result


def mark_event_handled(db: Session, payment_id: str) -> dict:
    p = db.get(SimPayment, payment_id)
    return {"outcome": "duplicate_dropped", "ledger_entries": len(p.ledger_entries)}


def late_success(db: Session, payment_id: str) -> None:
    """The processor finally reports the timed-out capture as successful."""
    p = db.get(SimPayment, payment_id)
    p.processor_status = "captured"
    p.processor_feed_lag_s = 0
    p.processor_as_of = utcnow()
    if not p.captures:
        p.captures = [{"key": p.original_idempotency_key, "at": utcnow().isoformat() + "Z", "late": True}]
