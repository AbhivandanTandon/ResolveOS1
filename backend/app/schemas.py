from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

UTC = Annotated[datetime, PlainSerializer(lambda d: d.isoformat() + "Z", return_type=str)]
Role = Literal["operator", "approver", "compliance", "admin"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------- requests

class LoginIn(BaseModel):
    email: str = Field(max_length=200)


class RejectIn(BaseModel):
    reason: Literal["Too risky", "Wrong cause", "Evidence is stale", "Conflicts with policy",
                    "Needs more information", "Other"]
    note: str | None = Field(default=None, max_length=1000)


class EventIn(BaseModel):
    event_key: str = Field(min_length=3, max_length=120)
    payment_id: str = Field(max_length=40)
    type: str = Field(max_length=60)
    source: str = "processor"
    payload: dict = Field(default_factory=dict)


class ScenarioIn(BaseModel):
    case_id: str | None = None
    merchant: str | None = Field(default=None, max_length=120)


class ConfigIn(BaseModel):
    evidence_max_age_s: int | None = Field(default=None, ge=30, le=3600)
    risk_auto_max: int | None = Field(default=None, ge=0, le=60)
    max_retries: int | None = Field(default=None, ge=0, le=5)
    max_rejections: int | None = Field(default=None, ge=1, le=10)
    auto_run_allowlist: list[str] | None = None


class KillSwitchIn(BaseModel):
    enabled: bool
    confirm: str = Field(description='Must be "PAUSE" to turn on and "RESUME" to turn off.')


class RoleIn(BaseModel):
    role: Role


# ---------------------------------------------------------------- responses

class UserOut(ORM):
    id: int
    email: str
    name: str
    role: str


class LoginOut(BaseModel):
    token: str
    user: UserOut


class CaseSummary(ORM):
    id: str
    payment_id: str
    merchant: str
    amount_minor: int
    currency: str
    processor: str
    exception_type: str
    issue: str
    status: str
    route: str | None
    risk_score: int | None
    round: int
    rejection_count: int
    owner: str
    simulated: bool
    created_at: UTC
    updated_at: UTC
    resolved_at: UTC | None


class EvidenceOut(ORM):
    id: int
    source: str
    label: str
    summary: str
    data: dict
    source_ref: str | None
    observed_at: UTC
    fetched_at: UTC
    current: bool
    age_s: int = 0
    stale: bool = False


class GateCheck(BaseModel):
    status: Literal["ok", "warn", "block"]
    code: str
    message: str


class RecommendationOut(ORM):
    id: int
    round: int
    rank: int
    action_type: str
    title: str
    description: str
    rationale: str
    moves_money: bool
    risk_score: int
    risk_detail: dict = {}
    gate_decision: str
    gate_checks: list[GateCheck]
    status: str
    status_reason: str | None
    idempotency_key: str | None
    created_at: UTC


class DiagnosisOut(ORM):
    id: int
    round: int
    summary: str
    detail: str
    root_cause: str
    confidence: float
    model: str
    retrieved: list[dict]
    security_flags: list[dict]
    usage: dict = {}
    ml: dict = {}
    created_at: UTC


class DecisionOut(BaseModel):
    id: int
    recommendation_id: int
    decision: str
    reason: str | None
    note: str | None
    user: str
    role: str
    created_at: UTC


class ExecutionOut(ORM):
    id: int
    recommendation_id: int
    idempotency_key: str
    status: str
    result: dict
    verified: bool
    verification: dict
    executed_by: str
    started_at: UTC
    finished_at: UTC | None


class AuditOut(ORM):
    id: int
    case_id: str | None
    kind: str
    actor: str
    tool: str | None
    summary: str
    data: dict
    created_at: UTC


class CaseDetail(BaseModel):
    case: CaseSummary
    diagnosis: DiagnosisOut | None
    recommendations: list[RecommendationOut]
    history: list[RecommendationOut]
    evidence: list[EvidenceOut]
    decisions: list[DecisionOut]
    executions: list[ExecutionOut]
    timeline: list[AuditOut]
    permissions: dict


class KnowledgeHit(BaseModel):
    doc_id: str
    type: str
    title: str
    body: str
    source: str
    trusted: bool
    tags: list[str]
    score: float | None
    retrieval: str
    security_flags: list[str]
    dense_score: float | None = None
    lexical_score: float | None = None
    source_url: str | None = None
    source_tier: str | None = None


class ConfigOut(BaseModel):
    kill_switch: bool
    evidence_max_age_s: int
    risk_auto_max: int
    max_retries: int
    max_rejections: int
    auto_run_allowlist: list[str]
    llm: dict
