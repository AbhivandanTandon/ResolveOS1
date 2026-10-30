from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:  # pgvector on PostgreSQL, JSON everywhere else
    from pgvector.sqlalchemy import Vector

    EmbeddingType = JSON().with_variant(Vector(384), "postgresql")
except ImportError:  # pragma: no cover
    EmbeddingType = JSON()

from .db import Base, utcnow

ROLES = ("operator", "approver", "compliance", "admin")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    role: Mapped[str] = mapped_column(String(20))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class PaymentCase(Base):
    __tablename__ = "payment_cases"
    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    payment_id: Mapped[str] = mapped_column(String(40), index=True)
    merchant: Mapped[str] = mapped_column(String(120))
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    processor: Mapped[str] = mapped_column(String(40))
    exception_type: Mapped[str] = mapped_column(String(40), default="unclassified")
    issue: Mapped[str] = mapped_column(String(200))
    # investigating | awaiting_approval | needs_evidence | blocked | executing | monitoring | resolved | escalated
    status: Mapped[str] = mapped_column(String(30), default="investigating", index=True)
    # auto_run | human_approval | more_evidence | hard_block
    route: Mapped[str | None] = mapped_column(String(20), nullable=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    rejection_count: Mapped[int] = mapped_column(Integer, default=0)
    owner: Mapped[str] = mapped_column(String(120), default="Priya Nair")
    scenario: Mapped[str | None] = mapped_column(String(40), nullable=True)
    simulated: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    recommendations: Mapped[list["Recommendation"]] = relationship(back_populates="case", order_by="Recommendation.id")


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_key: Mapped[str] = mapped_column(String(120), unique=True)  # dedupe key
    case_id: Mapped[str | None] = mapped_column(ForeignKey("payment_cases.id"), nullable=True, index=True)
    payment_id: Mapped[str] = mapped_column(String(40), index=True)
    source: Mapped[str] = mapped_column(String(40))
    type: Mapped[str] = mapped_column(String(60))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    duplicate_count: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("payment_cases.id"), index=True)
    source: Mapped[str] = mapped_column(String(40))  # processor | ledger | history | screening | event_log | bank
    label: Mapped[str] = mapped_column(String(80))
    summary: Mapped[str] = mapped_column(String(300))
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    source_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime)  # when the source says the data is true
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    current: Mapped[bool] = mapped_column(Boolean, default=True)


class Diagnosis(Base):
    __tablename__ = "diagnoses"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("payment_cases.id"), index=True)
    round: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    root_cause: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[float] = mapped_column(Float)
    model: Mapped[str] = mapped_column(String(120))
    output: Mapped[dict] = mapped_column(JSON)  # validated structured output
    retrieved: Mapped[list] = mapped_column(JSON, default=list)
    security_flags: Mapped[list] = mapped_column(JSON, default=list)
    # {"prompt_tokens", "completion_tokens", "calls", "cost_usd" (null when no price is configured)}
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    # ML second opinions: {"triage": {...}, "action": {...}, "features": {...}, "retrieval": "..."}
    ml: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("payment_cases.id"), index=True)
    diagnosis_id: Mapped[int] = mapped_column(ForeignKey("diagnoses.id"))
    round: Mapped[int] = mapped_column(Integer)
    rank: Mapped[int] = mapped_column(Integer)
    action_type: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text, default="")
    moves_money: Mapped[bool] = mapped_column(Boolean)
    risk_score: Mapped[int] = mapped_column(Integer)
    # {"scorer": "lightgbm-calibrated" | "heuristic-v1", "probability": float | None, "level": str}
    risk_detail: Mapped[dict] = mapped_column(JSON, default=dict)
    gate_decision: Mapped[str] = mapped_column(String(20))
    gate_checks: Mapped[list] = mapped_column(JSON, default=list)
    # proposed | approved | rejected | executed | invalidated | superseded | blocked
    status: Mapped[str] = mapped_column(String(20), default="proposed", index=True)
    status_reason: Mapped[str | None] = mapped_column(String(300), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    evidence_snapshot: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    case: Mapped[PaymentCase] = relationship(back_populates="recommendations")


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("payment_cases.id"), index=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    decision: Mapped[str] = mapped_column(String(10))  # approve | reject
    reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Execution(Base):
    __tablename__ = "executions"
    __table_args__ = (UniqueConstraint("recommendation_id", name="uq_execution_once"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("payment_cases.id"), index=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id"))
    idempotency_key: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | succeeded | failed | blocked
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verification: Mapped[dict] = mapped_column(JSON, default=dict)
    executed_by: Mapped[str] = mapped_column(String(120))
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"
    id: Mapped[int] = mapped_column(primary_key=True)
    doc_id: Mapped[str] = mapped_column(String(60), unique=True)
    type: Mapped[str] = mapped_column(String(30))  # policy | runbook | error_code | past_case | merchant_note
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(120))
    trusted: Mapped[bool] = mapped_column(Boolean, default=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    # Dense BGE vector (384-d): pgvector on PostgreSQL, JSON on SQLite.
    embedding: Mapped[list | None] = mapped_column(EmbeddingType, nullable=True)
    added_by: Mapped[str] = mapped_column(String(120), default="seed")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    kind: Mapped[str] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(120))
    tool: Mapped[str | None] = mapped_column(String(80), nullable=True)
    summary: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class SystemConfig(Base):
    __tablename__ = "system_config"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict | list | int | float | bool | str] = mapped_column(JSON)
    updated_by: Mapped[str] = mapped_column(String(120), default="system")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SimPayment(Base):
    """State of the simulated processor and ledger. Nothing here is a real payment."""

    __tablename__ = "sim_payments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))
    processor: Mapped[str] = mapped_column(String(40))
    # what the processor reports right now: pending | captured | failed | held | returned | declined | scheduled
    processor_status: Mapped[str] = mapped_column(String(20))
    processor_as_of: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    processor_feed_lag_s: Mapped[int] = mapped_column(Integer, default=0)  # >0 = processor serves a cached status
    ledger_status: Mapped[str] = mapped_column(String(20))  # none | captured | debited | not_settled | settled
    ledger_entries: Mapped[list] = mapped_column(JSON, default=list)
    captures: Mapped[list] = mapped_column(JSON, default=list)  # every capture the processor performed
    idempotency_results: Mapped[dict] = mapped_column(JSON, default=dict)
    original_idempotency_key: Mapped[str | None] = mapped_column(String(80), nullable=True)
    compliance_hold: Mapped[bool] = mapped_column(Boolean, default=False)
    retries_used: Mapped[int] = mapped_column(Integer, default=0)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
