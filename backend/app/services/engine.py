"""Case lifecycle: ingest events, investigate, route, approve/reject, execute once, verify, re-evaluate."""

import logging
import time
import uuid
from functools import partial
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import AuditEvent, Decision, Diagnosis, Evidence, Execution, PaymentCase, PaymentEvent, Recommendation, SimPayment, User
from . import knowledge, llm, ml, processor, risk
from .actions import spec
from .safety_gate import (AUTO_RUN, HARD_BLOCK, HUMAN_APPROVAL, MORE_EVIDENCE, REQUIRED_SOURCES, EvidenceView,
                          GateContext, evaluate, states_conflict)
from .system import audit, get_config, hub

try:
    from langgraph.graph import END, StateGraph
except ImportError:  # pragma: no cover
    StateGraph = None

log = logging.getLogger("resolveos.engine")
AGENT = "ResolveOS agent"
OPEN_STATUSES = ("investigating", "awaiting_approval", "needs_evidence", "blocked", "executing", "monitoring")
CASE_OPENING_EVENTS = {"capture.timeout", "screening.hold", "settlement.file", "transfer.cutoff_missed",
                       "transfer.returned", "chargeback.notice", "authorization.declined", "ledger.mismatch"}
_SYMBOL = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}


class EngineError(Exception):
    def __init__(self, status: int, code: str, message: str, detail: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.detail = status, code, message, detail or {}


def fmt_amount(minor: int, currency: str) -> str:
    return f"{_SYMBOL.get(currency, currency + ' ')}{minor / 100:,.2f}"


# ---------------------------------------------------------------- evidence

def current_evidence(db: Session, case_id: str) -> list[Evidence]:
    return list(db.scalars(select(Evidence).where(Evidence.case_id == case_id, Evidence.current.is_(True))
                           .order_by(Evidence.id)))


def _replace_evidence(db: Session, case: PaymentCase, source: str, **kw) -> Evidence:
    for old in db.scalars(select(Evidence).where(Evidence.case_id == case.id, Evidence.source == source,
                                                 Evidence.current.is_(True))):
        old.current = False
    ev = Evidence(case_id=case.id, source=source, fetched_at=utcnow(), current=True, **kw)
    db.add(ev)
    return ev


def gather_evidence(db: Session, case: PaymentCase) -> None:
    p = processor.read_processor(db, case.payment_id)
    audit(db, case.id, "evidence", "Processor API (simulated)", f"Processor status {p['status']}",
          tool="get_payment_status", data={"status": p["status"], "as_of": p["as_of"].isoformat() + "Z"})
    _replace_evidence(db, case, "processor", label="Processor status",
                      summary=f"{p['status'].capitalize()}" + (", not confirmed" if p["status"] == "pending" else ""),
                      data={"status": p["status"], "captures": p["captures"]}, observed_at=p["as_of"],
                      source_ref=f"sim://{case.processor}/payments/{case.payment_id}")
    lg = processor.read_ledger(db, case.payment_id)
    n = len(lg["entries"])
    audit(db, case.id, "evidence", "Ledger (simulated)", f"Ledger status {lg['status']}, {n} entries",
          tool="get_ledger_entries", data={"status": lg["status"], "entries": n})
    _replace_evidence(db, case, "ledger", label="Ledger",
                      summary="No entry for this payment" if n == 0 else f"{n} entr{'y' if n == 1 else 'ies'}, status {lg['status']}",
                      data={"status": lg["status"], "entries": lg["entries"]}, observed_at=lg["as_of"],
                      source_ref=f"sim://ledger/{case.payment_id}")
    sim = db.get(SimPayment, case.payment_id)
    if sim.compliance_hold:
        _replace_evidence(db, case, "screening", label="Screening result",
                          summary=sim.meta.get("screening", "Possible watch-list match"),
                          data={"hold": True}, observed_at=utcnow(), source_ref="sim://screening")
    events = list(db.scalars(select(PaymentEvent).where(PaymentEvent.payment_id == case.payment_id)))
    dups = sum(e.duplicate_count for e in events)
    _replace_evidence(db, case, "event_log", label="Event log",
                      summary=f"{len(events)} event(s)" + (f", {dups} duplicate(s) dropped" if dups else ""),
                      data={"events": [e.type for e in events], "duplicates": dups}, observed_at=utcnow(),
                      source_ref=f"sim://events/{case.payment_id}")


def _views(evs: list[Evidence]) -> list[EvidenceView]:
    return [EvidenceView(e.source, e.observed_at, e.data) for e in evs]


def _evidence_state(db: Session, case: PaymentCase, cfg: dict) -> dict:
    evs = current_evidence(db, case.id)
    by = {e.source: e for e in evs}
    now = utcnow()
    proc = by.get("processor").data.get("status") if "processor" in by else None
    ledger = by.get("ledger").data.get("status") if "ledger" in by else None
    stale = any((now - by[s].observed_at).total_seconds() > cfg["evidence_max_age_s"] for s in REQUIRED_SOURCES if s in by)
    missing = [s for s in REQUIRED_SOURCES if s not in by]
    return {"evidence": evs, "processor_status": proc, "ledger_status": ledger, "stale": stale,
            "missing": missing, "conflict": states_conflict(proc, ledger)}


def gate_for(db: Session, case: PaymentCase, action_type: str, risk_score: int, cfg: dict | None = None):
    cfg = cfg or get_config(db)
    st = _evidence_state(db, case, cfg)
    sim = db.get(SimPayment, case.payment_id)
    a = spec(action_type)
    has_key = bool(sim.original_idempotency_key) if a and a.is_retry else True
    ctx = GateContext(now=utcnow(), kill_switch=bool(cfg["kill_switch"]), compliance_hold=sim.compliance_hold,
                      evidence=_views(st["evidence"]), processor_status=st["processor_status"],
                      ledger_status=st["ledger_status"], risk_score=risk_score, retries_used=sim.retries_used,
                      max_retries=cfg["max_retries"], has_idempotency_key=has_key,
                      evidence_max_age_s=cfg["evidence_max_age_s"], risk_auto_max=cfg["risk_auto_max"],
                      auto_run_allowlist=cfg["auto_run_allowlist"])
    return evaluate(action_type, ctx)


# ---------------------------------------------------------------- investigation graph

class InvState(TypedDict, total=False):
    case_id: str
    trigger: str
    pace: float
    exception_type: str
    ev: dict
    retrieved: list
    security_flags: list
    output: dict
    model: str
    model_notes: list
    usage: dict
    ml_triage: dict
    ml_action: dict
    ml_features: dict
    ml_defaults: list
    options: list
    route: str


def _pause(state):
    if state.get("pace"):
        time.sleep(state["pace"])


def _case_text(db: Session, case: PaymentCase) -> str:
    """Free text in the shape the triage model was trained on: "[RAIL] processor message | note: ..."."""
    first = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == case.payment_id).order_by(PaymentEvent.id))
    p = first.payload if first else {}
    rail = ml.nb_rail(case.processor, case.currency)
    msg = " ".join(str(p[k]) for k in ("issue", "error") if p.get(k)) or case.issue
    note = p.get("note") or ""
    return f"[{rail}] {msg}" + (f" | note: {note}" if note else "")


def _n_triage(db: Session, state: InvState) -> dict:
    case = db.get(PaymentCase, state["case_id"])
    if case.exception_type == "unclassified":
        first = db.scalar(select(PaymentEvent).where(PaymentEvent.payment_id == case.payment_id).order_by(PaymentEvent.id))
        case.exception_type, who = llm.classify(first.type if first else "", first.payload if first else {})
    else:
        who = "rules"
    pred = None
    if ml.runtime.ready:
        try:
            pred = ml.runtime.classify(_case_text(db, case))
            if case.exception_type == "unclassified" and pred["mapped"] and pred["p"] >= 0.6:
                case.exception_type, who = pred["mapped"], "ml"
        except Exception as e:
            log.warning("ML triage failed: %s", e)
    audit(db, case.id, "triage", {"ml": "BGE triage model", "rules": "Rules classifier"}.get(who, "Nemotron Nano"),
          f"Classified as {case.exception_type.replace('_', ' ')}", tool="classify_exception",
          data={"exception_type": case.exception_type, "trigger": state["trigger"]})
    if pred:
        sim = db.get(SimPayment, case.payment_id)
        expected = ml.nb_exception(case.exception_type, sim.processor_status)
        verdict = "agrees" if pred["label"] == expected else f"differs (rules: {expected or 'no equivalent'})"
        audit(db, case.id, "triage", "BGE triage model",
              f"Second opinion: {pred['label']} {pred['p']:.2f}, {verdict}", tool="ml_triage", data=pred)
    _pause(state)
    return {"exception_type": case.exception_type, "ml_triage": pred or {}}


def _n_evidence(db: Session, state: InvState) -> dict:
    case = db.get(PaymentCase, state["case_id"])
    gather_evidence(db, case)
    db.flush()
    st = _evidence_state(db, case, get_config(db))
    _pause(state)
    return {"ev": {k: v for k, v in st.items() if k != "evidence"}}


def _n_retrieve(db: Session, state: InvState) -> dict:
    case = db.get(PaymentCase, state["case_id"])
    q = f"{state['exception_type'].replace('_', ' ')} {case.issue} {state['ev']['processor_status'] or ''} {case.merchant}"
    hits = knowledge.search(db, q, k=8, exc_type=state["exception_type"])
    flags, kept = [], []
    for h in hits:
        if h["security_flags"]:
            flags.append({"doc_id": h["doc_id"], "patterns": h["security_flags"], "action": "quarantined"})
            audit(db, case.id, "security", "Prompt-injection filter",
                  f"Quarantined {h['doc_id']} ({h['source']}): instruction-like text in a retrieved document",
                  tool="scan_untrusted", data={"doc_id": h["doc_id"], "patterns": h["security_flags"]})
        else:
            kept.append(h)
    audit(db, case.id, "retrieval", "Hybrid RAG (BGE + TF-IDF, RRF)" if ml.runtime.ready else "Knowledge search (BM25)", ", ".join(f"{h['doc_id']} {h['score']:.2f}" for h in kept[:3])
          or "No matches", tool="search_knowledge", data={"query": q, "results": [
              {"doc_id": h["doc_id"], "score": h["score"], "retrieval": h["retrieval"],
               "dense": h.get("dense_score"), "lexical": h.get("lexical_score")} for h in kept]})
    _pause(state)
    return {"retrieved": kept, "security_flags": flags}


def _rejections(db: Session, case_id: str) -> tuple[list[str], list[str]]:
    rows = db.execute(select(Recommendation.action_type, Decision.note).join(Decision, Decision.recommendation_id == Recommendation.id)
                      .where(Decision.case_id == case_id, Decision.decision == "reject")).all()
    return [r[0] for r in rows], [r[1] for r in rows if r[1]]


def _n_diagnose(db: Session, state: InvState) -> dict:
    case = db.get(PaymentCase, state["case_id"])
    rejected, notes = _rejections(db, case.id)
    notes += [n for n in db.scalars(select(AuditEvent.summary).where(AuditEvent.case_id == case.id,
                                                                    AuditEvent.kind == "note"))]
    flags = list(state.get("security_flags", []))
    for n in notes:
        pats = knowledge.scan_for_injection(n)
        if pats:
            flags.append({"source": "operator_note", "patterns": pats, "action": "wrapped as data"})
    ev = state["ev"]
    ctx = {
        "exception_type": state["exception_type"], "processor_status": ev["processor_status"],
        "ledger_status": ev["ledger_status"], "stale": ev["stale"], "conflict": ev["conflict"],
        "amount": fmt_amount(case.amount_minor, case.currency), "processor": case.processor, "owner": case.owner,
        "rejected_actions": rejected, "operator_notes": notes,
        "evidence_labels": [e.label for e in current_evidence(db, case.id)],
        "evidence_summaries": [f"{e.label}: {e.summary}" for e in current_evidence(db, case.id)],
    }
    feats, defaults, pred = _ml_features(db, case, ev)
    if pred:
        ctx["ml_signals"] = {"action_prediction": {"label": pred["label"], "p": pred["p"], "maps_to": pred["actions"]},
                             "triage": {k: state.get("ml_triage", {}).get(k) for k in ("label", "p")}}
        ctx["invariants"] = ml.runtime.kb.meta.get("invariants")
    high = case.exception_type in ("compliance_hold", "conflicting_state") or case.rejection_count > 0 \
        or case.amount_minor >= 500_000
    out, model, mnotes, usage = llm.diagnose(ctx, state.get("retrieved", []), high)
    audit(db, case.id, "diagnosis", model, f"{out.summary} Confidence {round(out.confidence * 100)}%.",
          tool="diagnose", data={"root_cause": out.root_cause, "options": [o.action_type for o in out.options],
                                 "notes": mnotes, "usage": usage})
    if pred:
        top = out.options[0].action_type
        verdict = "agrees with option 1" if top in pred["actions"] \
            else f"differs from option 1 ({top.replace('_', ' ').lower()})"
        audit(db, case.id, "diagnosis", "LightGBM action predictor",
              f"Second opinion: {pred['label']} {pred['p']:.2f}, {verdict}", tool="predict_action",
              data={**pred, "defaults_used": defaults})
    _pause(state)
    return {"output": out.model_dump(), "model": model, "model_notes": mnotes, "security_flags": flags,
            "usage": usage, "ml_action": pred or {}, "ml_features": feats or {}, "ml_defaults": defaults}


def _ml_features(db: Session, case: PaymentCase, ev: dict) -> tuple[dict | None, list, dict | None]:
    """Notebook-format features for the risk and action models, or (None, [], None) when ML is off."""
    if not ml.runtime.ready:
        return None, [], None
    try:
        sim = db.get(SimPayment, case.payment_id)
        now = utcnow()
        ages = [(now - e.observed_at).total_seconds() / 60 for e in current_evidence(db, case.id)
                if e.source in REQUIRED_SOURCES]
        pending = db.scalar(select(func.count()).select_from(Recommendation).where(
            Recommendation.case_id == case.id, Recommendation.moves_money.is_(True),
            Recommendation.status.in_(("proposed", "approved", "invalidated")))) or 0
        feats, defaults = ml.runtime.features(
            exception_type=case.exception_type, processor=case.processor, currency=case.currency,
            amount_minor=case.amount_minor, processor_status=ev["processor_status"], ledger_status=ev["ledger_status"],
            retries_used=sim.retries_used, evidence_age_min=max(ages, default=0.0), hold=sim.compliance_hold,
            conflict=ev["conflict"], idempotency_ok=bool(sim.original_idempotency_key), pending_action=pending > 0,
            created_at=case.created_at,
            tier="corporate" if case.processor in ("Bank rail", "Processor B") else "retail")
        return feats, defaults, ml.runtime.predict_action(feats)
    except Exception as e:
        log.warning("ML features failed: %s", e)
        return None, [], None


def _n_risk(db: Session, state: InvState) -> dict:
    case = db.get(PaymentCase, state["case_id"])
    sim = db.get(SimPayment, case.payment_id)
    ev = state["ev"]
    opts = []
    feats = state.get("ml_features") or None
    for i, o in enumerate(state["output"]["options"]):
        a = spec(o["action_type"])
        detail = None
        if feats:
            try:
                label = ml.nb_action(a.type, ml.nb_exception(case.exception_type, ev["processor_status"]))
                p = ml.runtime.risk_probability(feats, label)
                s = ml.probability_to_score(p, ml.runtime.risk_thresholds)
                detail = {"scorer": "lightgbm-calibrated", "probability": round(p, 3), "level": risk.level(s),
                          "model_action": label}
            except Exception as e:
                log.warning("ML risk failed, using heuristic: %s", e)
        if detail is None:
            f = risk.features(amount_minor=case.amount_minor, currency=case.currency, exception_type=case.exception_type,
                              processor_status=ev["processor_status"], conflict=ev["conflict"], stale=ev["stale"],
                              compliance_hold=sim.compliance_hold, moves_money=a.moves_money,
                              rejections=case.rejection_count)
            s, scorer = risk.score(f)
            detail = {"scorer": scorer, "probability": None, "level": risk.level(s)}
        opts.append({**o, "rank": i + 1, "risk": s, "scorer": detail["scorer"], "risk_detail": detail,
                     "moves_money": a.moves_money})
    d0 = opts[0]["risk_detail"]
    prob = f" (p={d0['probability']:.2f})" if d0["probability"] is not None else ""
    audit(db, case.id, "risk", "LightGBM risk model (calibrated)" if feats else "Risk heuristic",
          f"Risk {opts[0]['risk']}{prob}, {d0['level']} for option 1",
          tool="score_risk", data={"scores": [o["risk"] for o in opts], "scorer": d0["scorer"],
                                   "probabilities": [o["risk_detail"]["probability"] for o in opts],
                                   "features": feats, "defaults_used": state.get("ml_defaults", [])})
    _pause(state)
    return {"options": opts}


def _n_gate(db: Session, state: InvState) -> dict:
    case = db.get(PaymentCase, state["case_id"])
    cfg = get_config(db)
    sim = db.get(SimPayment, case.payment_id)
    opts = []
    for o in state["options"]:
        g = gate_for(db, case, o["action_type"], o["risk"], cfg)
        opts.append({**o, "gate": g.as_dict()})
    ev = state["ev"]
    top = opts[0]["gate"]["decision"]
    if sim.compliance_hold or cfg["kill_switch"]:
        route = HARD_BLOCK
    elif ev["stale"] or ev["missing"] or (ev["conflict"] and opts[0]["moves_money"]) or \
            opts[0]["action_type"] == "REFRESH_EVIDENCE":
        route = MORE_EVIDENCE
    else:
        route = top
    concerns = "; ".join(c["message"] for c in opts[0]["gate"]["checks"] if c["status"] != "ok")
    audit(db, case.id, "gate", "Safety gate (plain code, no model)",
          f"Route: {route.replace('_', ' ')}" + (f". {concerns}" if concerns else ""), tool="check_gate", data={"route": route, "decisions": [o["gate"]["decision"] for o in opts]})
    return {"options": opts, "route": route}


_NODES = [("triage", _n_triage), ("gather_evidence", _n_evidence), ("retrieve", _n_retrieve),
          ("diagnose", _n_diagnose), ("score_risk", _n_risk), ("safety_gate", _n_gate)]


def _run_graph(db: Session, state: InvState) -> InvState:
    if StateGraph is None:
        for _, fn in _NODES:
            state.update(fn(db, state))
        return state
    g = StateGraph(InvState)
    for name, fn in _NODES:
        g.add_node(name, partial(fn, db))
    g.set_entry_point(_NODES[0][0])
    for (a, _), (b, _) in zip(_NODES, _NODES[1:]):
        g.add_edge(a, b)
    g.add_edge(_NODES[-1][0], END)
    return g.compile().invoke(state)


def investigate(db: Session, case: PaymentCase, trigger: str, pace: float = 0.0) -> None:
    case.status = "investigating"
    db.flush()
    hub.publish("case.updated", case_id=case.id)
    st = _run_graph(db, {"case_id": case.id, "trigger": trigger, "pace": pace})
    out = st["output"]
    diag = Diagnosis(case_id=case.id, round=case.round, summary=out["summary"], detail=out["detail"],
                     root_cause=out["root_cause"], confidence=out["confidence"], model=st["model"], output=out,
                     retrieved=[{k: r.get(k) for k in ("doc_id", "type", "title", "source", "score", "trusted",
                                                       "retrieval", "dense_score", "lexical_score", "source_url")}
                                for r in st.get("retrieved", [])],
                     security_flags=st.get("security_flags", []), usage=st.get("usage") or {},
                     ml={"triage": st.get("ml_triage") or None, "action": st.get("ml_action") or None,
                         "features": st.get("ml_features") or None, "defaults_used": st.get("ml_defaults") or [],
                         "retrieval": "hybrid" if ml.runtime.ready else "bm25"})
    db.add(diag)
    db.flush()
    for old in db.scalars(select(Recommendation).where(Recommendation.case_id == case.id,
                                                       Recommendation.status == "proposed")):
        old.status, old.status_reason = "superseded", f"Replaced by round {case.round} plan"
    snapshot = [{"id": e.id, "source": e.source, "observed_at": e.observed_at.isoformat() + "Z"}
                for e in current_evidence(db, case.id)]
    sim = db.get(SimPayment, case.payment_id)
    recs = []
    for o in st["options"]:
        a = spec(o["action_type"])
        key = sim.original_idempotency_key if a.is_retry else (f"{case.id}-{a.type}-{uuid.uuid4().hex[:8]}"
                                                                if a.moves_money else None)
        r = Recommendation(case_id=case.id, diagnosis_id=diag.id, round=case.round, rank=o["rank"],
                           action_type=a.type, title=o["title"], description=o["description"],
                           rationale=o.get("rationale", ""), moves_money=a.moves_money, risk_score=o["risk"],
                           risk_detail=o["risk_detail"],
                           gate_decision=o["gate"]["decision"], gate_checks=o["gate"]["checks"],
                           status="blocked" if o["gate"]["decision"] == HARD_BLOCK else "proposed",
                           idempotency_key=key, evidence_snapshot=snapshot)
        db.add(r)
        recs.append(r)
    db.flush()
    case.route = st["route"]
    case.risk_score = recs[0].risk_score
    top = recs[0]
    if top.gate_decision == AUTO_RUN:
        audit(db, case.id, "routing", AGENT, f"Auto-run: {top.title}", data={"recommendation_id": top.id})
        execute(db, case, top, actor=f"{AGENT} (auto-run)")
    else:
        case.status = {HARD_BLOCK: "blocked", MORE_EVIDENCE: "needs_evidence"}.get(st["route"], "awaiting_approval")
        audit(db, case.id, "routing", AGENT, {
            "blocked": "Hard block: no action may run",
            "needs_evidence": "Waiting for fresh, consistent evidence",
            "awaiting_approval": f"Waiting for a person to approve: {top.title}",
        }[case.status], data={"recommendation_id": top.id})
    hub.publish("case.updated", case_id=case.id)


# ---------------------------------------------------------------- events

def _next_case_id(db: Session) -> str:
    ids = [int(i.split("-")[1]) for i in db.scalars(select(PaymentCase.id))]
    return f"PAY-{max(ids, default=48187) + 1}"


def ingest_event(db: Session, ev: dict, pace: float = 0.0) -> dict:
    """Ingest one processor/bank event. Duplicate event keys are dropped and audited."""
    existing = db.scalar(select(PaymentEvent).where(PaymentEvent.event_key == ev["event_key"]))
    if existing is not None:
        existing.duplicate_count += 1
        case = existing.case_id and db.get(PaymentCase, existing.case_id)
        if not case:
            case = db.scalar(select(PaymentCase).where(PaymentCase.payment_id == ev["payment_id"]))
        opened = False
        if case is None and existing.type == "payment.captured":
            # A repeated money event with no open case: open one so a person can see it was handled.
            case = _open_case(db, ev, "duplicate_event", f"Duplicate webhook event {ev['event_key']}")
            existing.case_id = case.id
            audit(db, case.id, "event", "Event intake", f"Event received: {ev['type']} ({ev['event_key']})",
                  data={"event_key": ev["event_key"]})
            opened = True
        audit(db, case.id if case else None, "event", "Duplicate filter",
              f"Duplicate event {ev['event_key']} dropped before triage", tool="dedupe",
              data={"event_key": ev["event_key"], "count": existing.duplicate_count + 1})
        if opened:
            investigate(db, case, "duplicate event", pace)
        db.commit()
        return {"duplicate": True, "case_id": case.id if case else None}

    row = PaymentEvent(event_key=ev["event_key"], payment_id=ev["payment_id"], source=ev.get("source", "processor"),
                       type=ev["type"], payload=ev.get("payload", {}))
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return ingest_event(db, ev, pace)

    sim = db.get(SimPayment, ev["payment_id"])
    if ev["type"] == "payment.captured" and sim:
        sim.processor_status, sim.ledger_status = "captured", "captured"
        if not sim.ledger_entries:
            processor._ledger_add(sim, "capture", f"from event {ev['event_key']}")
    elif ev["type"] == "capture.succeeded" and sim:
        processor.late_success(db, sim.id)
    elif ev["type"] == "capture.failed" and sim:
        sim.processor_status = "failed"

    case = db.scalar(select(PaymentCase).where(PaymentCase.payment_id == ev["payment_id"])
                     .order_by(PaymentCase.created_at.desc()))
    if case is not None:
        row.case_id = case.id
        audit(db, case.id, "event", f"{case.processor} (simulated)", f"Event received: {ev['type']}",
              tool="ingest_event", data={"event_key": ev["event_key"], "payload": ev.get("payload", {})})
        if case.status in OPEN_STATUSES:
            reevaluate(db, case, f"late event {ev['type']}", pace)
    elif ev["type"] in CASE_OPENING_EVENTS:
        p = ev.get("payload", {})
        case = _open_case(db, ev, llm.EVENT_TO_EXCEPTION.get(ev["type"], "unclassified"), p.get("issue", ev["type"]))
        row.case_id = case.id
        audit(db, case.id, "event", f"{case.processor} (simulated)", f"Event received: {p.get('issue', ev['type'])}",
              tool="ingest_event", data={"event_key": ev["event_key"], "payload": p})
        audit(db, case.id, "event", "Duplicate filter", "Duplicate check passed", tool="dedupe")
        investigate(db, case, "new exception", pace)
    db.commit()
    hub.publish("case.updated", case_id=case.id if case else None)
    return {"duplicate": False, "case_id": case.id if case else None}


def _open_case(db: Session, ev: dict, exception_type: str, issue: str) -> PaymentCase:
    sim = db.get(SimPayment, ev["payment_id"])
    p = ev.get("payload", {})
    case = PaymentCase(id=_next_case_id(db), payment_id=ev["payment_id"], merchant=p.get("merchant", "Unknown merchant"),
                       amount_minor=sim.amount_minor, currency=sim.currency, processor=sim.processor,
                       exception_type=exception_type, issue=issue, owner=p.get("owner", "Priya Nair"),
                       scenario=p.get("scenario"), status="investigating")
    db.add(case)
    db.flush()
    return case


def reevaluate(db: Session, case: PaymentCase, reason: str, pace: float = 0.0) -> None:
    """Payment state changed: cancel stale proposals, then investigate again with fresh evidence."""
    open_recs = list(db.scalars(select(Recommendation).where(Recommendation.case_id == case.id,
                                                             Recommendation.status.in_(("proposed", "approved")))))
    sim = db.get(SimPayment, case.payment_id)
    for r in open_recs:
        r.status = "invalidated"
        why = f"Payment state changed ({reason}); processor now reports {sim.processor_status}"
        if r.action_type == "RETRY_CAPTURE" and sim.processor_status == "captured":
            why = "Stale retry cancelled: the processor already captured this payment, a retry could charge twice"
        r.status_reason = why
        audit(db, case.id, "invalidation", AGENT, f"Invalidated: {r.title}. {why}", data={"recommendation_id": r.id})
    case.round += 1
    investigate(db, case, reason, pace)


# ---------------------------------------------------------------- decisions

MONEY_ROLES = {"approver", "admin"}


def _role_can_approve(user: User, case: PaymentCase, rec: Recommendation) -> bool:
    sim_hold = case.exception_type == "compliance_hold"
    if sim_hold:
        return user.role in ("compliance", "admin")
    if rec.moves_money:
        return user.role in MONEY_ROLES
    return user.role in ("operator", "approver", "admin")


def approve(db: Session, case: PaymentCase, rec: Recommendation, user: User) -> Execution:
    cfg = get_config(db)
    if cfg["kill_switch"]:
        raise EngineError(423, "KILL_SWITCH", "The agent is paused by the kill switch. No action can be approved.")
    if rec.case_id != case.id or rec.status != "proposed" or rec.round != case.round:
        raise EngineError(409, "NOT_PROPOSED", f"This recommendation is {rec.status} and can no longer be approved.")
    if not _role_can_approve(user, case, rec):
        raise EngineError(403, "FORBIDDEN_ROLE", f"A {user.role} cannot approve this action.")
    g = gate_for(db, case, rec.action_type, rec.risk_score, cfg)
    rec.gate_decision, rec.gate_checks = g.decision, g.checks
    if g.decision == HARD_BLOCK:
        audit(db, case.id, "gate", "Safety gate (plain code, no model)", f"Approval refused: {rec.title} is hard-blocked",
              data={"checks": g.checks, "user": user.name})
        db.commit()
        raise EngineError(403, "HARD_BLOCK", "The safety gate blocks this action.", {"checks": g.checks})
    if g.decision == MORE_EVIDENCE and not spec(rec.action_type).read_only:
        audit(db, case.id, "gate", "Safety gate (plain code, no model)",
              f"Approval refused: evidence is stale or conflicting for {rec.title}", data={"checks": g.checks})
        db.commit()
        raise EngineError(409, "EVIDENCE_STALE", "Evidence is stale or conflicting. Refresh it before approving.",
                          {"checks": g.checks})
    db.add(Decision(case_id=case.id, recommendation_id=rec.id, user_id=user.id, decision="approve"))
    rec.status = "approved"
    audit(db, case.id, "decision", user.name, f"Approved: {rec.title}", tool="approve",
          data={"recommendation_id": rec.id, "role": user.role})
    return execute(db, case, rec, actor=user.name)


def reject(db: Session, case: PaymentCase, rec: Recommendation, user: User, reason: str, note: str | None,
           pace: float = 0.0) -> None:
    cfg = get_config(db)
    if rec.case_id != case.id or rec.status != "proposed":
        raise EngineError(409, "NOT_PROPOSED", f"This recommendation is {rec.status} and can no longer be rejected.")
    if user.role not in ("operator", "approver", "compliance", "admin"):
        raise EngineError(403, "FORBIDDEN_ROLE", "Your role cannot reject recommendations.")
    db.add(Decision(case_id=case.id, recommendation_id=rec.id, user_id=user.id, decision="reject", reason=reason,
                    note=(note or "").strip()[:1000] or None))
    rec.status, rec.status_reason = "rejected", reason
    case.rejection_count += 1
    audit(db, case.id, "decision", user.name, f"Rejected: {rec.title} ({reason})", tool="reject",
          data={"recommendation_id": rec.id, "reason": reason, "note": note, "count": case.rejection_count})
    if case.rejection_count >= cfg["max_rejections"]:
        for r in db.scalars(select(Recommendation).where(Recommendation.case_id == case.id,
                                                         Recommendation.status == "proposed")):
            r.status, r.status_reason = "superseded", "Case escalated after repeated rejections"
        case.status = "escalated"
        audit(db, case.id, "escalation", AGENT,
              f"{case.rejection_count} rejections: escalated to {case.owner}", data={"owner": case.owner})
        db.commit()
        hub.publish("case.updated", case_id=case.id)
        return
    case.round += 1
    investigate(db, case, f"rejection: {reason}", pace)
    db.commit()


# ---------------------------------------------------------------- execution

def execute(db: Session, case: PaymentCase, rec: Recommendation, actor: str) -> Execution:
    """Run an authorized recommendation exactly once, then re-read the real state to verify."""
    existing = db.scalar(select(Execution).where(Execution.recommendation_id == rec.id))
    if existing is not None:
        audit(db, case.id, "execution", actor, f"Repeat execution request ignored: {rec.title} already ran once",
              data={"execution_id": existing.id})
        db.commit()
        return existing
    cfg = get_config(db)
    g = gate_for(db, case, rec.action_type, rec.risk_score, cfg)
    a = spec(rec.action_type)
    allowed = g.decision in (AUTO_RUN, HUMAN_APPROVAL) or (g.decision == MORE_EVIDENCE and a.read_only)
    authorized = rec.status == "approved" or g.decision == AUTO_RUN
    exe = Execution(case_id=case.id, recommendation_id=rec.id, idempotency_key=f"exec-{rec.id}", executed_by=actor,
                    status="running")
    db.add(exe)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return db.scalar(select(Execution).where(Execution.recommendation_id == rec.id))
    if not (allowed and authorized):
        exe.status, exe.finished_at = "blocked", utcnow()
        exe.result = {"gate": g.as_dict(), "authorized": authorized}
        rec.status, rec.status_reason = "blocked", "Blocked by the safety gate at execution time"
        audit(db, case.id, "gate", "Safety gate (plain code, no model)", f"Execution blocked: {rec.title}",
              data=g.as_dict())
        case.status = "blocked" if g.decision == HARD_BLOCK else "needs_evidence"
        db.commit()
        hub.publish("case.updated", case_id=case.id)
        return exe

    case.status = "executing"
    audit(db, case.id, "execution", actor, f"Running once: {rec.title}", tool=rec.action_type.lower(),
          data={"idempotency_key": rec.idempotency_key, "execution_key": exe.idempotency_key})
    pid = case.payment_id
    t = rec.action_type
    rerun = False
    if t == "RETRY_CAPTURE":
        exe.result = processor.capture(db, pid, rec.idempotency_key)
    elif t == "RECONCILE_WITH_PROCESSOR":
        processor.read_processor(db, pid)
        exe.result = processor.reconcile(db, pid)
    elif t == "REFRESH_EVIDENCE":
        exe.result = processor.refresh_feed(db, pid)
        rerun = True
    elif t == "DROP_DUPLICATE_EVENT":
        exe.result = processor.mark_event_handled(db, pid)
    elif t in ("RESUBMIT_NEXT_WINDOW", "CORRECT_AND_RESUBMIT"):
        exe.result = processor.resubmit(db, pid, rec.idempotency_key, rec.title)
    elif t in ("ESCALATE_TO_OWNER", "ESCALATE_TO_COMPLIANCE"):
        who = "Compliance queue" if t == "ESCALATE_TO_COMPLIANCE" else case.owner
        exe.result = {"outcome": "escalated", "to": who}
    else:
        exe.result = {"outcome": "message_logged", "simulated": True}
    exe.status = "succeeded"
    rec.status = "executed"
    db.flush()

    # Verify against the real (simulated) state, never against what we expected to happen.
    gather_evidence(db, case)
    db.flush()
    st = _evidence_state(db, case, cfg)
    sim = db.get(SimPayment, pid)
    proc, ledger = st["processor_status"], st["ledger_status"]
    v = {"processor_status": proc, "ledger_status": ledger, "captures": len(sim.captures), "consistent": not st["conflict"]}
    if t in ("ESCALATE_TO_OWNER", "ESCALATE_TO_COMPLIANCE"):
        exe.verified = True
        case.status = "escalated"
        v["note"] = f"Case assigned to {exe.result['to']}"
    elif t == "RETRY_CAPTURE":
        exe.verified = proc == "captured" and ledger == "captured" and len(sim.captures) == 1
        case.status = "resolved" if exe.verified else "escalated"
    elif t == "RECONCILE_WITH_PROCESSOR" and exe.result.get("outcome") == "still_pending":
        exe.verified = True
        case.status = "monitoring"
        v["note"] = "Processor still pending; watching for the final event"
    elif t == "REFRESH_EVIDENCE":
        exe.verified = True
    elif t in ("REQUEST_MERCHANT_INFO", "ADD_CASE_NOTE"):
        exe.verified = True
        case.status = "monitoring"
    else:
        exe.verified = not st["conflict"]
        case.status = "resolved" if exe.verified else "escalated"
    exe.verification = v
    exe.finished_at = utcnow()
    if case.status == "resolved":
        case.resolved_at = utcnow()
    if case.status in ("resolved", "escalated"):
        for r in db.scalars(select(Recommendation).where(Recommendation.case_id == case.id,
                                                         Recommendation.status == "proposed")):
            r.status, r.status_reason = "superseded", f"Case {case.status}"
    audit(db, case.id, "verification", "State verifier",
          ("Verified" if exe.verified else "Verification FAILED") +
          f": processor {proc}, ledger {ledger}, {len(sim.captures)} capture(s)", tool="verify_state", data=v)
    db.commit()
    hub.publish("case.updated", case_id=case.id)
    if rerun:
        case.round += 1
        investigate(db, case, "fresh evidence")
        db.commit()
    return exe


def refresh_evidence(db: Session, case: PaymentCase, user: User) -> None:
    """Operator asks for more evidence: re-read every source and investigate again."""
    audit(db, case.id, "decision", user.name, "Requested fresh evidence", tool="request_evidence")
    rec = db.scalar(select(Recommendation).where(Recommendation.case_id == case.id, Recommendation.status == "proposed",
                                                 Recommendation.action_type == "REFRESH_EVIDENCE"))
    if rec is not None:
        rec.status = "approved"
        db.add(Decision(case_id=case.id, recommendation_id=rec.id, user_id=user.id, decision="approve"))
        execute(db, case, rec, actor=user.name)
        return
    case.round += 1
    investigate(db, case, "evidence requested")
    db.commit()


def case_counts(db: Session) -> dict:
    rows = db.execute(select(PaymentCase.status, func.count()).group_by(PaymentCase.status)).all()
    return {s: n for s, n in rows}
