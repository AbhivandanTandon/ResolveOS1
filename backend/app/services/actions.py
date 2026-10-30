"""Registry of every action the system knows how to perform.

Model output may only reference action types listed here; anything else is discarded before it
reaches the safety gate. Properties here are facts about the action, not model opinions.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    type: str
    label: str
    moves_money: bool
    read_only: bool
    # Allowed to run without a human when the gate's auto-run conditions are met.
    auto_run_eligible: bool = False
    # The only actions allowed while a compliance hold is active.
    allowed_under_hold: bool = False
    # Never allowed for the agent, whatever the evidence says.
    prohibited: bool = False
    is_retry: bool = False
    # No side effects on money or the outside world, so the payment's risk score does not limit auto-run.
    risk_exempt: bool = False


ACTIONS: dict[str, ActionSpec] = {
    a.type: a
    for a in [
        ActionSpec("RETRY_CAPTURE", "Retry the capture", moves_money=True, read_only=False, is_retry=True),
        ActionSpec("RECONCILE_WITH_PROCESSOR", "Reconcile with the processor", moves_money=False, read_only=False,
                   auto_run_eligible=True),
        ActionSpec("REFRESH_EVIDENCE", "Refresh evidence", moves_money=False, read_only=True, auto_run_eligible=True,
                   risk_exempt=True),
        ActionSpec("DROP_DUPLICATE_EVENT", "Drop the duplicate event", moves_money=False, read_only=False,
                   auto_run_eligible=True),
        ActionSpec("RESUBMIT_NEXT_WINDOW", "Resubmit for the next settlement window", moves_money=True, read_only=False),
        ActionSpec("CORRECT_AND_RESUBMIT", "Correct details and resubmit", moves_money=True, read_only=False),
        ActionSpec("REQUEST_MERCHANT_INFO", "Ask the merchant for information", moves_money=False, read_only=True),
        ActionSpec("NOTIFY_CUSTOMER", "Notify the customer", moves_money=False, read_only=True, auto_run_eligible=True),
        ActionSpec("ESCALATE_TO_OWNER", "Escalate to the case owner", moves_money=False, read_only=True,
                   allowed_under_hold=True),
        ActionSpec("ESCALATE_TO_COMPLIANCE", "Escalate to compliance", moves_money=False, read_only=True,
                   auto_run_eligible=True, allowed_under_hold=True, risk_exempt=True),
        ActionSpec("ADD_CASE_NOTE", "Add a note for the reviewer", moves_money=False, read_only=True,
                   allowed_under_hold=True),
        ActionSpec("RELEASE_HOLD", "Release the compliance hold", moves_money=True, read_only=False, prohibited=True),
        ActionSpec("REFUND", "Refund the payment", moves_money=True, read_only=False),
    ]
}


def spec(action_type: str) -> ActionSpec | None:
    return ACTIONS.get(action_type)
