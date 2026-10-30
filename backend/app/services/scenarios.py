"""Simulator scenarios. Every payment here is synthetic and flagged as simulated."""

import random
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import PaymentCase, SimPayment
from .engine import EngineError, OPEN_STATUSES, ingest_event
from .system import audit

SCENARIOS = {
    "network_timeout": {"name": "Network timeout", "description": "Card capture times out; the processor may have captured it anyway."},
    "duplicate_event": {"name": "Duplicate event", "description": "The same webhook arrives twice; the copy must be dropped."},
    "late_success": {"name": "Late success", "description": "The processor confirms a timed-out capture. Stale retries must be cancelled."},
    "sanctions_hold": {"name": "Sanctions hold", "description": "Screening holds the payment. Hard block, escalate only."},
    "processor_cutoff": {"name": "Processor cut-off", "description": "A bank transfer misses the settlement cut-off."},
    "stale_evidence": {"name": "Stale evidence", "description": "Processor status is 31 minutes old and disagrees with the ledger."},
    "conflicting_state": {"name": "Conflicting states", "description": "The ledger shows a capture the processor says failed."},
    "returned_transfer": {"name": "Returned transfer", "description": "The bank returns a transfer: bad account number format."},
    "chargeback_no_order": {"name": "Chargeback, no order", "description": "A chargeback arrives for a reference with no order."},
    "issuer_decline": {"name": "Issuer decline", "description": "The card is declined for insufficient funds. Low risk, auto-run."},
}

_MERCHANTS = ["Acme Retail", "Northbeam Books", "Harbor Goods", "Pinecrest Outdoor", "Orbit Coffee", "Vela Apparel"]


def _sim(db: Session, amount_minor: int, currency: str, processor: str, **kw) -> SimPayment:
    pid = f"pi_{uuid.uuid4().hex[:10]}"
    p = SimPayment(id=pid, amount_minor=amount_minor, currency=currency, processor=processor,
                   processor_as_of=utcnow(), ledger_entries=[], captures=[], idempotency_results={}, meta={}, **kw)
    db.add(p)
    db.flush()
    return p


def run(db: Session, key: str, pace: float = 0.0, case_id: str | None = None, overrides: dict | None = None) -> dict:
    if key not in SCENARIOS:
        raise EngineError(404, "UNKNOWN_SCENARIO", f"Unknown scenario {key}")
    o = overrides or {}
    merchant = o.get("merchant") or random.choice(_MERCHANTS)
    owner = o.get("owner", "Priya Nair")
    tag = uuid.uuid4().hex[:6]
    audit(db, None, "simulator", "Simulator lab", f"Scenario started: {SCENARIOS[key]['name']}", data={"scenario": key})

    if key == "network_timeout":
        p = _sim(db, o.get("amount_minor", random.choice([124000, 56000, 213050])), o.get("currency", "USD"),
                 "Processor A", processor_status="pending", ledger_status="none",
                 original_idempotency_key=f"idem_{tag}")
        return ingest_event(db, {"event_key": f"evt_timeout_{tag}", "payment_id": p.id, "type": "capture.timeout",
                                 "payload": {"merchant": merchant, "owner": owner, "scenario": key,
                                             "issue": "Network timeout on card capture",
                                             "error": "Timed out after 30 seconds, no response"}}, pace)

    if key == "duplicate_event":
        p = _sim(db, o.get("amount_minor", 8650), o.get("currency", "USD"), "Processor A",
                 processor_status="captured", ledger_status="none", original_idempotency_key=f"idem_{tag}")
        ev = {"event_key": f"evt_{tag}", "payment_id": p.id, "type": "payment.captured",
              "payload": {"merchant": merchant, "owner": owner, "scenario": key}}
        ingest_event(db, ev, pace)
        return ingest_event(db, ev, pace)

    if key == "late_success":
        case = db.get(PaymentCase, case_id) if case_id else db.scalar(
            select(PaymentCase).where(PaymentCase.exception_type == "network_timeout",
                                      PaymentCase.status.in_(OPEN_STATUSES)).order_by(PaymentCase.created_at.desc()))
        if case is None:
            raise EngineError(409, "NO_TARGET", "No open network-timeout case to receive a late success event.")
        return ingest_event(db, {"event_key": f"evt_late_{case.payment_id}", "payment_id": case.payment_id,
                                 "type": "capture.succeeded",
                                 "payload": {"scenario": key, "note": f"{case.processor} reports the capture succeeded"}},
                            pace)

    if key == "sanctions_hold":
        p = _sim(db, o.get("amount_minor", 1890000), o.get("currency", "EUR"), "Processor B",
                 processor_status="held", ledger_status="none", compliance_hold=True,
                 original_idempotency_key=f"idem_{tag}")
        p.meta = {"screening": "Possible watch-list match on the beneficiary, confidence 0.88"}
        return ingest_event(db, {"event_key": f"evt_hold_{tag}", "payment_id": p.id, "type": "screening.hold",
                                 "payload": {"merchant": o.get("merchant", "Kestrel Travel"), "owner": owner,
                                             "scenario": key, "issue": "Sanctions screening hold"}}, pace)

    if key == "processor_cutoff":
        p = _sim(db, o.get("amount_minor", 930000), o.get("currency", "USD"), "Bank rail",
                 processor_status="failed", ledger_status="none", original_idempotency_key=f"idem_{tag}")
        p.meta = {"cutoff": "16:00", "submitted": "16:07"}
        return ingest_event(db, {"event_key": f"evt_cutoff_{tag}", "payment_id": p.id, "type": "transfer.cutoff_missed",
                                 "payload": {"merchant": o.get("merchant", "Lumen Pay Supplies"), "owner": owner,
                                             "scenario": key, "issue": "Bank cut-off missed"}}, pace)

    if key == "stale_evidence":
        p = _sim(db, o.get("amount_minor", 48200000), o.get("currency", "INR"), "Processor C",
                 processor_status="settled", processor_feed_lag_s=31 * 60, ledger_status="not_settled",
                 original_idempotency_key=f"idem_{tag}")
        p.meta = {"live_status": "settled"}
        return ingest_event(db, {"event_key": f"evt_settle_{tag}", "payment_id": p.id, "type": "settlement.file",
                                 "payload": {"merchant": o.get("merchant", "Saffron Foods"), "owner": owner,
                                             "scenario": key, "issue": "Processor status out of date"}}, pace)
    simple = {
        "conflicting_state": (dict(amount_minor=31500, currency="USD", processor="Processor A",
                                   processor_status="failed", ledger_status="captured"),
                              "ledger.mismatch", "Harbor Goods", "Ledger shows a capture the processor rejected"),
        "returned_transfer": (dict(amount_minor=41500, currency="USD", processor="Bank rail",
                                   processor_status="returned", ledger_status="none"),
                              "transfer.returned", "Cardwave Studio", "Bank transfer returned, bad account format"),
        "chargeback_no_order": (dict(amount_minor=5820, currency="USD", processor="Processor A",
                                     processor_status="chargeback", ledger_status="none"),
                                "chargeback.notice", "Dockside Cafe", "Chargeback notice with no matching order"),
        "issuer_decline": (dict(amount_minor=21200, currency="GBP", processor="Processor A",
                                processor_status="declined", ledger_status="none"),
                           "authorization.declined", "Ridgeway Electronics", "Issuer decline, insufficient funds"),
    }
    if key in simple:
        attrs, event_type, default_merchant, issue = simple[key]
        attrs = {**attrs, **{k: o[k] for k in ("amount_minor", "currency") if k in o}}
        amount, currency, proc = attrs.pop("amount_minor"), attrs.pop("currency"), attrs.pop("processor")
        p = _sim(db, amount, currency, proc, original_idempotency_key=f"idem_{tag}", **attrs)
        if key == "conflicting_state":
            p.ledger_entries = [{"kind": "capture", "amount_minor": amount, "currency": currency,
                                 "at": utcnow().isoformat() + "Z", "note": "posted from an optimistic webhook"}]
        return ingest_event(db, {"event_key": f"evt_{key}_{tag}", "payment_id": p.id, "type": event_type,
                                 "payload": {"merchant": o.get("merchant", default_merchant), "owner": owner,
                                             "scenario": key, "issue": issue}}, pace)
    raise AssertionError(key)


def seed_demo(db: Session) -> None:
    run(db, "stale_evidence")
    run(db, "processor_cutoff")
    run(db, "sanctions_hold")
    run(db, "duplicate_event", overrides={"merchant": "Northbeam Books"})
    run(db, "returned_transfer")
    run(db, "chargeback_no_order")
    run(db, "network_timeout", overrides={"merchant": "Acme Retail", "amount_minor": 124000})
    db.commit()
