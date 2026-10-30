from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..auth import current_user, require_roles
from ..db import get_db, utcnow
from ..models import AuditEvent, Decision, Diagnosis, Evidence, Execution, PaymentCase, Recommendation, User
from ..schemas import (AuditOut, CaseDetail, CaseSummary, DecisionOut, DiagnosisOut, EvidenceOut, ExecutionOut,
                       RecommendationOut, RejectIn)
from ..services import engine
from ..services.actions import spec
from ..services.system import get_config

router = APIRouter(prefix="/api/cases", tags=["cases"])


def _case(db: Session, case_id: str) -> PaymentCase:
    c = db.get(PaymentCase, case_id)
    if c is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"Case {case_id} not found."})
    return c


def _rec(db: Session, case: PaymentCase, rec_id: int) -> Recommendation:
    r = db.get(Recommendation, rec_id)
    if r is None or r.case_id != case.id:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Recommendation not found."})
    return r


@router.get("", response_model=list[CaseSummary], summary="List cases")
def list_cases(q: str | None = None, status: str | None = None, route: str | None = None,
               limit: int = Query(default=200, ge=1, le=1000), offset: int = Query(default=0, ge=0),
               db: Session = Depends(get_db), _: User = Depends(current_user)):
    stmt = select(PaymentCase).order_by(PaymentCase.created_at.desc())
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(PaymentCase.id.ilike(like), PaymentCase.merchant.ilike(like),
                              PaymentCase.issue.ilike(like), PaymentCase.payment_id.ilike(like)))
    if status:
        stmt = stmt.where(PaymentCase.status.in_(status.split(",")))
    if route:
        stmt = stmt.where(PaymentCase.route.in_(route.split(",")))
    return list(db.scalars(stmt.limit(limit).offset(offset)))


def build_detail(db: Session, case: PaymentCase, user: User) -> CaseDetail:
    cfg = get_config(db)
    now = utcnow()
    evs = []
    for e in db.scalars(select(Evidence).where(Evidence.case_id == case.id, Evidence.current.is_(True))
                        .order_by(Evidence.id)):
        out = EvidenceOut.model_validate(e)
        out.age_s = int((now - e.observed_at).total_seconds())
        out.stale = e.source in ("processor", "ledger") and out.age_s > cfg["evidence_max_age_s"]
        evs.append(out)
    diag = db.scalar(select(Diagnosis).where(Diagnosis.case_id == case.id).order_by(Diagnosis.id.desc()))
    recs = list(db.scalars(select(Recommendation).where(Recommendation.case_id == case.id).order_by(Recommendation.id)))
    current = [r for r in recs if r.round == case.round and r.status in ("proposed", "blocked", "approved", "executed")]
    history = [r for r in recs if r not in current]
    decisions = [
        DecisionOut(id=d.id, recommendation_id=d.recommendation_id, decision=d.decision, reason=d.reason, note=d.note,
                    user=u.name, role=u.role, created_at=d.created_at)
        for d, u in db.execute(select(Decision, User).join(User, User.id == Decision.user_id)
                               .where(Decision.case_id == case.id).order_by(Decision.id)).all()
    ]
    execs = list(db.scalars(select(Execution).where(Execution.case_id == case.id).order_by(Execution.id)))
    timeline = list(db.scalars(select(AuditEvent).where(AuditEvent.case_id == case.id).order_by(AuditEvent.id)))
    top = next((r for r in current if r.status == "proposed"), None)
    hold = case.exception_type == "compliance_hold"
    can_approve = bool(top) and not cfg["kill_switch"] and (
        user.role in ("compliance", "admin") if hold else
        user.role in ("approver", "admin") if top.moves_money else user.role in ("operator", "approver", "admin"))
    return CaseDetail(
        case=CaseSummary.model_validate(case),
        diagnosis=DiagnosisOut.model_validate(diag) if diag else None,
        recommendations=[RecommendationOut.model_validate(r) for r in sorted(current, key=lambda r: r.rank)],
        history=[RecommendationOut.model_validate(r) for r in history],
        evidence=evs, decisions=decisions,
        executions=[ExecutionOut.model_validate(x) for x in execs],
        timeline=[AuditOut.model_validate(t) for t in timeline],
        permissions={"approve": can_approve, "reject": bool(top),
                     "refresh_evidence": user.role in ("operator", "approver", "admin"),
                     "kill_switch": bool(cfg["kill_switch"]), "max_rejections": cfg["max_rejections"],
                     "evidence_max_age_s": cfg["evidence_max_age_s"]},
    )


@router.get("/{case_id}", response_model=CaseDetail, summary="Case details, evidence, plan and timeline")
def get_case(case_id: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return build_detail(db, _case(db, case_id), user)


@router.get("/{case_id}/timeline", response_model=list[AuditOut], summary="Case timeline (audit events)")
def timeline(case_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    _case(db, case_id)
    return list(db.scalars(select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id)))


@router.get("/{case_id}/recommendations", response_model=list[RecommendationOut], summary="All proposed actions")
def recommendations(case_id: str, db: Session = Depends(get_db), _: User = Depends(current_user)):
    _case(db, case_id)
    return list(db.scalars(select(Recommendation).where(Recommendation.case_id == case_id).order_by(Recommendation.id)))


@router.get("/{case_id}/recommendations/{rec_id}/gate", summary="Re-run the safety gate for a recommendation now")
def gate_now(case_id: str, rec_id: int, db: Session = Depends(get_db), _: User = Depends(current_user)):
    case = _case(db, case_id)
    r = _rec(db, case, rec_id)
    return {"recommendation_id": r.id, **engine.gate_for(db, case, r.action_type, r.risk_score).as_dict(),
            "action": {"type": r.action_type, "moves_money": spec(r.action_type).moves_money}}


@router.post("/{case_id}/investigate", response_model=CaseDetail, summary="Start or restart the investigation")
def investigate(case_id: str, db: Session = Depends(get_db),
                user: User = Depends(require_roles("operator", "approver", "admin"))):
    case = _case(db, case_id)
    if case.status in ("resolved", "escalated"):
        raise HTTPException(409, detail={"code": "CLOSED", "message": "Case is closed."})
    engine.audit(db, case.id, "decision", user.name, "Restarted the investigation", tool="investigate")
    case.round += 1
    engine.investigate(db, case, f"manual restart by {user.name}")
    db.commit()
    return build_detail(db, case, user)


@router.post("/{case_id}/evidence/refresh", response_model=CaseDetail, summary="Request more evidence")
def refresh(case_id: str, db: Session = Depends(get_db),
            user: User = Depends(require_roles("operator", "approver", "admin"))):
    case = _case(db, case_id)
    if case.status in ("resolved", "escalated"):
        raise HTTPException(409, detail={"code": "CLOSED", "message": "Case is closed."})
    engine.refresh_evidence(db, case, user)
    db.commit()
    return build_detail(db, case, user)


@router.post("/{case_id}/recommendations/{rec_id}/approve", response_model=CaseDetail,
             summary="Approve a recommendation; it then runs once and is verified")
def approve(case_id: str, rec_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = _case(db, case_id)
    engine.approve(db, case, _rec(db, case, rec_id), user)
    db.commit()
    return build_detail(db, case, user)


@router.post("/{case_id}/recommendations/{rec_id}/reject", response_model=CaseDetail,
             summary="Reject with a reason; a safer alternative is proposed")
def reject(case_id: str, rec_id: int, body: RejectIn, db: Session = Depends(get_db),
           user: User = Depends(current_user)):
    case = _case(db, case_id)
    engine.reject(db, case, _rec(db, case, rec_id), user, body.reason, body.note)
    db.commit()
    return build_detail(db, case, user)


@router.post("/{case_id}/recommendations/{rec_id}/execute", response_model=ExecutionOut,
             summary="Execute an approved recommendation (idempotent: repeats return the first execution)")
def execute(case_id: str, rec_id: int, db: Session = Depends(get_db),
            user: User = Depends(require_roles("approver", "admin"))):
    case = _case(db, case_id)
    r = _rec(db, case, rec_id)
    if r.status not in ("approved", "executed"):
        raise HTTPException(409, detail={"code": "NOT_APPROVED", "message": "Approve the recommendation first."})
    return engine.execute(db, case, r, actor=user.name)


@router.get("/{case_id}/replay", response_model=list[AuditOut], summary="Step-by-step replay of the case")
def replay(case_id: str, db: Session = Depends(get_db), _: User = Depends(current_user),
           upto: int | None = Query(default=None, description="Return events up to this audit id")):
    _case(db, case_id)
    stmt = select(AuditEvent).where(AuditEvent.case_id == case_id).order_by(AuditEvent.id)
    if upto:
        stmt = stmt.where(AuditEvent.id <= upto)
    return list(db.scalars(stmt))
