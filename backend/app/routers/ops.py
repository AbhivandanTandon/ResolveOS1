"""Case notes, audit export, knowledge curation and user management."""

import csv
import io
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import current_user, require_roles
from ..db import get_db
from ..models import AuditEvent, KnowledgeChunk, PaymentCase, User
from ..schemas import AuditOut, KnowledgeHit, Role, UserOut
from ..services import knowledge
from ..services.system import audit, hub

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------- case notes

class NoteIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.post("/cases/{case_id}/notes", response_model=AuditOut, tags=["cases"],
             summary="Add a human note to the case timeline (treated as untrusted data by the agent)")
def add_note(case_id: str, body: NoteIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if db.get(PaymentCase, case_id) is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": f"Case {case_id} not found."})
    flags = knowledge.scan_for_injection(body.text)
    ev = audit(db, case_id, "note", user.name, body.text.strip(), tool="add_note",
               data={"role": user.role, "security_flags": flags})
    db.commit()
    hub.publish("case.updated", case_id=case_id)
    return ev


# ---------------------------------------------------------------- audit export

@router.get("/audit/export", tags=["audit"], summary="Download the audit trail as CSV or JSON")
def export_audit(case_id: str | None = None, format: str = "csv", db: Session = Depends(get_db),
                 _: User = Depends(require_roles("approver", "compliance", "admin"))):
    stmt = select(AuditEvent).order_by(AuditEvent.id)
    if case_id:
        stmt = stmt.where(AuditEvent.case_id == case_id)
    rows = [AuditOut.model_validate(e).model_dump(mode="json") for e in db.scalars(stmt)]
    name = f"resolveos-audit-{case_id or 'all'}"
    if format == "json":
        return Response(json.dumps(rows, indent=2), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "created_at", "case_id", "kind", "actor", "tool", "summary", "data"])
    for r in rows:
        w.writerow([r["id"], r["created_at"], r["case_id"] or "", r["kind"], r["actor"], r["tool"] or "", r["summary"],
                    json.dumps(r["data"])])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ---------------------------------------------------------------- knowledge curation

class KnowledgeIn(BaseModel):
    type: str = Field(pattern="^(policy|runbook|error_code|past_case|merchant_note)$")
    title: str = Field(min_length=3, max_length=200)
    body: str = Field(min_length=10, max_length=4000)
    source: str = Field(min_length=2, max_length=120)
    tags: list[str] = Field(default_factory=list, max_length=12)
    trusted: bool = False


@router.post("/knowledge", response_model=KnowledgeHit, tags=["knowledge"], status_code=201,
             summary="Add a document. Only admins and compliance can mark it trusted.")
def add_doc(body: KnowledgeIn, db: Session = Depends(get_db),
            user: User = Depends(require_roles("operator", "approver", "compliance", "admin"))):
    trusted = body.trusted and user.role in ("admin", "compliance")
    flags = knowledge.scan_for_injection(body.body)
    if flags and trusted:
        raise HTTPException(422, detail={"code": "INJECTION_PATTERN",
                                         "message": "Text contains instruction-like patterns and cannot be trusted."})
    prefix = {"policy": "POL", "runbook": "RB", "error_code": "ERR", "past_case": "CASE", "merchant_note": "NOTE"}[body.type]
    slug = re.sub(r"[^A-Z0-9]+", "-", body.title.upper())[:16].strip("-")
    doc_id = f"{prefix}-{slug}"
    n = 1
    while db.scalar(select(KnowledgeChunk.id).where(KnowledgeChunk.doc_id == doc_id)):
        n += 1
        doc_id = f"{prefix}-{slug}-{n}"
    db.add(KnowledgeChunk(doc_id=doc_id, type=body.type, title=body.title, body=body.body, source=body.source,
                          tags=[t.strip().lower() for t in body.tags if t.strip()], trusted=trusted,
                          added_by=user.name))
    audit(db, None, "knowledge", user.name, f"Added {doc_id} ({'trusted' if trusted else 'untrusted'})",
          data={"doc_id": doc_id, "security_flags": flags})
    db.commit()
    return {"doc_id": doc_id, "type": body.type, "title": body.title, "body": body.body, "source": body.source,
            "trusted": trusted, "tags": body.tags, "score": None, "retrieval": "bm25", "security_flags": flags}


@router.delete("/knowledge/{doc_id}", tags=["knowledge"], status_code=204)
def delete_doc(doc_id: str, db: Session = Depends(get_db), user: User = Depends(require_roles("admin"))):
    row = db.scalar(select(KnowledgeChunk).where(KnowledgeChunk.doc_id == doc_id))
    if row is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "Document not found."})
    db.delete(row)
    audit(db, None, "knowledge", user.name, f"Removed {doc_id}")
    db.commit()
    return Response(status_code=204)


# ---------------------------------------------------------------- users

class UserIn(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$", max_length=200)
    name: str = Field(min_length=2, max_length=120)
    role: Role


class ActiveIn(BaseModel):
    active: bool


class AdminUserOut(UserOut):
    active: bool


@router.get("/admin/users/all", response_model=list[AdminUserOut], tags=["admin"])
def all_users(db: Session = Depends(get_db), _: User = Depends(require_roles("admin"))):
    return list(db.scalars(select(User).order_by(User.id)))


@router.post("/admin/users", response_model=AdminUserOut, tags=["admin"], status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    email = body.email.lower().strip()
    if db.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(409, detail={"code": "EXISTS", "message": "A user with that email already exists."})
    u = User(email=email, name=body.name.strip(), role=body.role)
    db.add(u)
    audit(db, None, "admin", admin.name, f"Created user {u.name} as {body.role}")
    db.commit()
    return u


@router.put("/admin/users/{user_id}/active", response_model=AdminUserOut, tags=["admin"])
def set_active(user_id: int, body: ActiveIn, db: Session = Depends(get_db), admin: User = Depends(require_roles("admin"))):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, detail={"code": "NOT_FOUND", "message": "User not found."})
    if u.id == admin.id and not body.active:
        raise HTTPException(409, detail={"code": "SELF_DEACTIVATE", "message": "You cannot deactivate yourself."})
    u.active = body.active
    audit(db, None, "admin", admin.name, f"{'Activated' if body.active else 'Deactivated'} {u.name}")
    db.commit()
    return u
