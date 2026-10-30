"""Auth, simulator/events, knowledge, metrics, audit and admin endpoints."""

import statistics
import threading

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import current_user, issue_token, require_roles
from ..config import settings
from ..db import SessionLocal, get_db
from ..models import AuditEvent, Diagnosis, Execution, PaymentCase, PaymentEvent, Recommendation, User
from ..schemas import (AuditOut, ConfigIn, ConfigOut, EventIn, KillSwitchIn, KnowledgeHit, LoginIn, LoginOut, RoleIn,
                       ScenarioIn, UserOut)
from ..services import benchmark, knowledge, llm, ml, scenarios
from ..services.actions import ACTIONS
from ..services.engine import EngineError, ingest_event
from ..services.system import audit, get_config, hub, set_config

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- auth

@router.get("/auth/users", response_model=list[UserOut], tags=["auth"], summary="Demo accounts for the sign-in screen")
def demo_users(db: Session = Depends(get_db)):
    return list(db.scalars(select(User).where(User.active.is_(True)).order_by(User.id)))


@router.post("/auth/login", response_model=LoginOut, tags=["auth"], summary="Mock sign-in as a seeded user")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.lower().strip()))
    if user is None or not user.active:
        raise HTTPException(401, detail={"code": "UNKNOWN_USER", "message": "No such user."})
    audit(db, None, "auth", user.name, f"Signed in as {user.role}")
    db.commit()
    return LoginOut(token=issue_token(user), user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut, tags=["auth"])
def me(user: User = Depends(current_user)):
    return user


# ---------------------------------------------------------------- events & simulator

@router.post("/events", tags=["events"], summary="Ingest a processor/bank event (deduplicated by event_key)")
def post_event(body: EventIn, db: Session = Depends(get_db),
               _: User = Depends(require_roles("operator", "approver", "admin"))):
    return ingest_event(db, body.model_dump())


@router.get("/simulator/scenarios", tags=["simulator"])
def list_scenarios(_: User = Depends(current_user)):
    return [{"key": k, **v} for k, v in scenarios.SCENARIOS.items()]


def _run_bg(key: str, body: ScenarioIn):
    db = SessionLocal()
    try:
        scenarios.run(db, key, pace=0.45 * settings.sim_delay_scale, case_id=body.case_id,
                      overrides={"merchant": body.merchant} if body.merchant else None)
        db.commit()
    except EngineError as e:
        db.rollback()
        hub.publish("simulator.error", scenario=key, message=e.message)
    except Exception as e:  # surface failures in the live feed instead of failing silently
        db.rollback()
        hub.publish("simulator.error", scenario=key, message=str(e))
        raise
    finally:
        db.close()


@router.post("/simulator/scenarios/{key}", tags=["simulator"], status_code=202,
             summary="Trigger a scenario; progress streams over /ws")
def trigger(key: str, body: ScenarioIn | None = None, db: Session = Depends(get_db),
            user: User = Depends(require_roles("operator", "approver", "admin"))):
    if key not in scenarios.SCENARIOS:
        raise HTTPException(404, detail={"code": "UNKNOWN_SCENARIO", "message": key})
    if key == "late_success" and body and body.case_id and db.get(PaymentCase, body.case_id) is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Case not found."})
    audit(db, None, "simulator", user.name, f"Triggered scenario {scenarios.SCENARIOS[key]['name']}")
    db.commit()
    threading.Thread(target=_run_bg, args=(key, body or ScenarioIn()), daemon=True).start()
    return {"accepted": True, "scenario": key}


# ---------------------------------------------------------------- knowledge

@router.get("/knowledge/search", response_model=list[KnowledgeHit], tags=["knowledge"])
def search(q: str = "", type: str | None = None, k: int = 20, include_background: bool = False,
           exception_type: str | None = None, db: Session = Depends(get_db), _: User = Depends(current_user)):
    """Hybrid search over the notebook KB (BGE + TF-IDF, RRF) fused with ResolveOS documents (BM25).
    Background sources (Wikipedia) are excluded unless include_background=true."""
    return knowledge.search(db, q, k=min(k, 50), doc_type=type, include_background=include_background,
                            exc_type=exception_type)


# ---------------------------------------------------------------- metrics

@router.get("/metrics", tags=["metrics"])
def metrics(db: Session = Depends(get_db), _: User = Depends(current_user)):
    cases = list(db.scalars(select(PaymentCase)))
    open_ = [c for c in cases if c.status not in ("resolved", "escalated")]
    resolved = [c for c in cases if c.status == "resolved" and c.resolved_at]
    durations = [(c.resolved_at - c.created_at).total_seconds() for c in resolved]
    execs = list(db.scalars(select(Execution)))
    blocked_recs = db.scalar(select(func.count()).select_from(Recommendation)
                             .where(Recommendation.moves_money.is_(True),
                                    Recommendation.gate_decision.in_(("hard_block", "more_evidence")))) or 0
    invalidated = db.scalar(select(func.count()).select_from(Recommendation)
                            .where(Recommendation.status == "invalidated")) or 0
    duplicates = db.scalar(select(func.sum(PaymentEvent.duplicate_count))) or 0
    quarantined = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.kind == "security")) or 0
    models = dict(db.execute(select(Diagnosis.model, func.count()).group_by(Diagnosis.model)).all())
    usages = [u for u in db.scalars(select(Diagnosis.usage)) if u]
    tokens = sum(u.get("prompt_tokens", 0) + u.get("completion_tokens", 0) for u in usages)
    calls = sum(u.get("calls", 0) for u in usages)
    priced = [u.get("cost_usd") for u in usages]
    cost = sum(priced) if priced and all(c is not None for c in priced) else (0.0 if not priced else None)
    by_route: dict[str, int] = {}
    for c in cases:
        by_route[c.route or "none"] = by_route.get(c.route or "none", 0) + 1
    by_status: dict[str, int] = {}
    for c in cases:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    return {
        "measured": {
            "label": "Measured on cases in this database (all simulated payments)",
            "cases_total": len(cases), "open": len(open_),
            "high_risk_open": sum(1 for c in open_ if (c.risk_score or 0) >= 75),
            "awaiting_approval": sum(1 for c in cases if c.status == "awaiting_approval"),
            "resolved": len(resolved),
            "median_resolution_s": statistics.median(durations) if durations else None,
            "executions": len(execs), "verified_executions": sum(1 for e in execs if e.verified),
            # Closed cases with every execution verified and no duplicate charge, over all closed cases.
            "safe_resolution_rate": (sum(1 for c in closed if all(
                e.verified and not e.result.get("duplicate_charge") for e in execs if e.case_id == c.id)) / len(closed))
            if (closed := [c for c in cases if c.status in ("resolved", "escalated")]) else None,
            "unsafe_actions_blocked": blocked_recs + invalidated,
            "money_actions_blocked_by_gate": blocked_recs, "stale_actions_invalidated": invalidated,
            "duplicate_events_dropped": duplicates, "injection_attempts_quarantined": quarantined,
            "tokens_total": tokens,
            "model_calls": calls,
            "cost_per_case_usd": (0.0 if not llm.llm_enabled() and not calls else
                                  round(cost / len(cases), 4) if cases and cost is not None else None),
            "cost_note": "Deterministic fallback: no model calls billed" if not calls
            else (f"{tokens:,} tokens metered" + ("" if cost is not None else "; set LLM_PRICE_PER_MTOK to price them")),
            "by_route": by_route, "by_status": by_status, "diagnosis_models": models,
        },
        "baselines": benchmark.run_suite(),
        "offline_eval": _offline_eval(),
    }


def _offline_eval() -> dict | None:
    """Results reported by the ML notebook (metrics.json). Synthetic and model-labelled, not production truth."""
    m = ml.runtime.metrics
    if not m:
        return None
    pick = lambda d, *ks: {k: d.get(k) for k in ks} if d else None  # noqa: E731
    return {
        "label": "Offline evaluation from the ML notebook export. Simulator labels are synthetic; real-text labels "
                 "are Nemotron-made. Neither is production ground truth.",
        "triage": pick(m.get("triage_embed_lr_sim_plus_real"), "test_macro_f1", "hard_acc", "hard_macro_f1"),
        "triage_real_heldout": pick(m.get("triage_sim_plus_real_on_real_heldout"), "acc", "macro_f1", "n"),
        "action": pick(m.get("action_predictor"), "test_acc", "test_macro_f1"),
        "risk": pick(m.get("risk_model"), "auc", "brier_calibrated", "ece_calibrated", "risk_level_acc"),
        "retrieval": m.get("retrieval_diagnostics"),
        "rag": m.get("rag_eval"),
        "rejection_flow": m.get("rejection_flow"),
        "models_used": m.get("models_used"),
    }


# ---------------------------------------------------------------- audit

@router.get("/audit", response_model=list[AuditOut], tags=["audit"])
def audit_log(case_id: str | None = None, kind: str | None = None, limit: int = 200, db: Session = Depends(get_db),
              _: User = Depends(current_user)):
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc()).limit(min(limit, 1000))
    if case_id:
        stmt = stmt.where(AuditEvent.case_id == case_id)
    if kind:
        stmt = stmt.where(AuditEvent.kind == kind)
    return list(db.scalars(stmt))


# ---------------------------------------------------------------- admin

def _config_out(db: Session) -> ConfigOut:
    return ConfigOut(**get_config(db), llm={
        "enabled": llm.llm_enabled(), "base_url": settings.nvidia_base_url,
        "models": {"ultra": settings.model_ultra, "super": settings.model_super, "nano": settings.model_nano},
        "fallback": "deterministic rules" if not llm.llm_enabled() else "used when a model call fails validation"})


@router.get("/admin/config", response_model=ConfigOut, tags=["admin"])
def get_cfg(db: Session = Depends(get_db), _: User = Depends(current_user)):
    return _config_out(db)


@router.put("/admin/config", response_model=ConfigOut, tags=["admin"])
def put_cfg(body: ConfigIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    changes = body.model_dump(exclude_none=True)
    if "auto_run_allowlist" in changes:
        bad = [a for a in changes["auto_run_allowlist"] if a not in ACTIONS or ACTIONS[a].moves_money
               or not ACTIONS[a].auto_run_eligible]
        if bad:
            raise HTTPException(422, detail={"code": "NOT_ELIGIBLE",
                                             "message": f"Not eligible for auto-run: {', '.join(bad)}"})
    for k, v in changes.items():
        set_config(db, k, v, user.name)
    audit(db, None, "admin", user.name, f"Updated safety policy: {', '.join(changes)}", data=changes)
    db.commit()
    hub.publish("config.updated")
    return _config_out(db)


@router.post("/admin/kill-switch", response_model=ConfigOut, tags=["admin"])
def kill_switch(body: KillSwitchIn, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    expected = "PAUSE" if body.enabled else "RESUME"
    if body.confirm != expected:
        raise HTTPException(400, detail={"code": "CONFIRMATION_REQUIRED", "message": f'Type "{expected}" to confirm.'})
    set_config(db, "kill_switch", body.enabled, user.name)
    audit(db, None, "admin", user.name, "Kill switch ON: all execution paused" if body.enabled else "Kill switch OFF")
    db.commit()
    hub.publish("config.updated", kill_switch=body.enabled)
    return _config_out(db)


@router.get("/admin/users", response_model=list[UserOut], tags=["admin"])
def users(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    return list(db.scalars(select(User).order_by(User.id)))


@router.put("/admin/users/{user_id}/role", response_model=UserOut, tags=["admin"])
def set_role(user_id: int, body: RoleIn, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "User not found."})
    if u.id == admin.id and body.role != "admin":
        raise HTTPException(409, detail={"code": "SELF_DEMOTE", "message": "You cannot remove your own admin role."})
    old, u.role = u.role, body.role
    audit(db, None, "admin", admin.name, f"Role for {u.name}: {old} → {body.role}")
    db.commit()
    return u


@router.get("/actions", tags=["admin"], summary="Action registry used by the safety gate")
def actions(_: User = Depends(current_user)):
    return [vars(a) for a in ACTIONS.values()]
