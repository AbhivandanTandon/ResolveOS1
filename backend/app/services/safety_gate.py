"""Deterministic safety gate.

Plain Python, no model calls. The LLM recommends; this module decides whether an action may run
automatically, needs a human, needs more evidence, or is blocked outright. It is evaluated when a
recommendation is created, again at approval time and again immediately before execution.
"""

from dataclasses import dataclass, field
from datetime import datetime

from .actions import spec

AUTO_RUN = "auto_run"
HUMAN_APPROVAL = "human_approval"
MORE_EVIDENCE = "more_evidence"
HARD_BLOCK = "hard_block"

_SEVERITY = {AUTO_RUN: 0, HUMAN_APPROVAL: 1, MORE_EVIDENCE: 2, HARD_BLOCK: 3}
FINAL_PROCESSOR_STATES = {"captured", "failed", "declined", "returned", "settled"}
REQUIRED_SOURCES = ("processor", "ledger")


@dataclass
class EvidenceView:
    source: str
    observed_at: datetime
    data: dict = field(default_factory=dict)


@dataclass
class GateContext:
    now: datetime
    kill_switch: bool
    compliance_hold: bool
    evidence: list[EvidenceView]
    processor_status: str | None
    ledger_status: str | None
    risk_score: int
    retries_used: int
    max_retries: int
    has_idempotency_key: bool
    evidence_max_age_s: int
    risk_auto_max: int
    auto_run_allowlist: list[str]


@dataclass
class GateResult:
    decision: str
    checks: list[dict]

    def as_dict(self) -> dict:
        return {"decision": self.decision, "checks": self.checks}


def _check(status: str, code: str, message: str) -> dict:
    return {"status": status, "code": code, "message": message}


def states_conflict(processor_status: str | None, ledger_status: str | None) -> bool:
    """Processor and ledger disagree about whether money moved."""
    if processor_status is None or ledger_status is None:
        return False
    proc_moved = processor_status in {"captured", "settled", "scheduled"}
    ledger_moved = ledger_status in {"captured", "settled", "debited"}
    if processor_status == "pending":
        return ledger_moved
    return proc_moved != ledger_moved


def evaluate(action_type: str, ctx: GateContext) -> GateResult:
    checks: list[dict] = []
    decision = AUTO_RUN

    def escalate(to: str):
        nonlocal decision
        if _SEVERITY[to] > _SEVERITY[decision]:
            decision = to

    a = spec(action_type)
    if a is None:
        return GateResult(HARD_BLOCK, [_check("block", "UNKNOWN_ACTION", f"Unknown action type {action_type!r}")])

    if ctx.kill_switch:
        escalate(HARD_BLOCK)
        checks.append(_check("block", "KILL_SWITCH", "Kill switch is on: no action can run"))

    if a.prohibited:
        escalate(HARD_BLOCK)
        checks.append(_check("block", "PROHIBITED", f"{a.label} is never allowed for the agent"))

    if ctx.compliance_hold:
        if a.allowed_under_hold:
            checks.append(_check("ok", "HOLD_ESCALATION", "Compliance hold: escalation path is allowed"))
        else:
            escalate(HARD_BLOCK)
            checks.append(_check("block", "COMPLIANCE_HOLD", "Compliance hold: the agent cannot release, retry or cancel"))
    else:
        checks.append(_check("ok", "NO_HOLD", "No compliance hold on this payment"))

    if a.moves_money:
        if ctx.has_idempotency_key:
            checks.append(_check("ok", "IDEMPOTENCY", "Idempotency key present"))
        else:
            escalate(HARD_BLOCK)
            checks.append(_check("block", "IDEMPOTENCY", "No idempotency key: money-moving action refused"))

    if a.is_retry:
        if ctx.retries_used >= ctx.max_retries:
            escalate(HARD_BLOCK)
            checks.append(_check("block", "RETRY_BUDGET", f"Retries used: {ctx.retries_used} of {ctx.max_retries}"))
        else:
            checks.append(_check("ok", "RETRY_BUDGET", f"Retries used: {ctx.retries_used} of {ctx.max_retries}"))
        if ctx.processor_status in FINAL_PROCESSOR_STATES - {"failed", "declined"}:
            escalate(HARD_BLOCK)
            checks.append(_check("block", "ALREADY_FINAL",
                                 f"Processor reports the payment as {ctx.processor_status}: a retry would duplicate it"))

    # Evidence freshness and completeness.
    by_source = {e.source: e for e in ctx.evidence}
    missing = [s for s in REQUIRED_SOURCES if s not in by_source]
    stale = [
        s for s, e in by_source.items()
        if s in REQUIRED_SOURCES and (ctx.now - e.observed_at).total_seconds() > ctx.evidence_max_age_s
    ]
    conflict = states_conflict(ctx.processor_status, ctx.ledger_status)
    if not a.read_only:
        if missing:
            escalate(MORE_EVIDENCE)
            checks.append(_check("warn", "EVIDENCE_MISSING", f"Missing evidence: {', '.join(missing)}"))
        if stale:
            escalate(MORE_EVIDENCE)
            checks.append(_check("warn", "EVIDENCE_STALE",
                                 f"Evidence older than {ctx.evidence_max_age_s}s: {', '.join(stale)}"))
        if conflict and a.moves_money:
            escalate(MORE_EVIDENCE)
            checks.append(_check("warn", "EVIDENCE_CONFLICT",
                                 f"Processor ({ctx.processor_status}) and ledger ({ctx.ledger_status}) disagree"))
        if not missing and not stale:
            checks.append(_check("ok", "EVIDENCE_FRESH", "Evidence is fresh"))

    if a.moves_money and ctx.processor_status in (None, "pending", "unknown"):
        escalate(HUMAN_APPROVAL)
        checks.append(_check("warn", "STATUS_UNCONFIRMED", "Processor status unconfirmed, so a person must approve"))

    if a.type == "RECONCILE_WITH_PROCESSOR" and ctx.processor_status not in FINAL_PROCESSOR_STATES:
        escalate(HUMAN_APPROVAL)
        checks.append(_check("warn", "NOT_FINAL", "Processor has no final status yet, reconcile needs a person"))
    if a.type == "RECONCILE_WITH_PROCESSOR" and ctx.processor_status in ("failed", "declined")             and ctx.ledger_status in ("captured", "settled", "debited"):
        escalate(HUMAN_APPROVAL)
        checks.append(_check("warn", "LEDGER_REVERSAL", "Reconciling would reverse a ledger entry, so a person must approve"))

    # Auto-run is opt-in: allowlisted, low risk, money never moves, evidence clean.
    auto_ok = (
        a.auto_run_eligible
        and a.type in ctx.auto_run_allowlist
        and not a.moves_money
        and (ctx.risk_score <= ctx.risk_auto_max or a.risk_exempt)
    )
    if decision == AUTO_RUN:
        if auto_ok:
            msg = "Allowlisted with no side effects, runs without a person" if ctx.risk_score > ctx.risk_auto_max \
                else f"Allowlisted and risk {ctx.risk_score} ≤ {ctx.risk_auto_max}"
            checks.append(_check("ok", "AUTO_RUN", msg))
        else:
            escalate(HUMAN_APPROVAL)
            why = "not on the auto-run allowlist" if a.type not in ctx.auto_run_allowlist or not a.auto_run_eligible \
                else f"risk {ctx.risk_score} above the auto-run limit {ctx.risk_auto_max}"
            checks.append(_check("warn", "NEEDS_HUMAN", f"Needs a person: {why}"))

    return GateResult(decision, checks)


def most_restrictive(decisions: list[str]) -> str:
    return max(decisions, key=lambda d: _SEVERITY[d]) if decisions else HUMAN_APPROVAL
