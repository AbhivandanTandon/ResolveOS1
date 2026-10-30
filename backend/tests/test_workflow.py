from datetime import timedelta

from app.db import SessionLocal
from app.models import Evidence, SimPayment
from app.services import scenarios


def run(key, **kw):
    with SessionLocal() as db:
        out = scenarios.run(db, key, **kw)
        db.commit()
        return out


def detail(client, h, case_id):
    return client.get(f"/api/cases/{case_id}", headers=h).json()


def top(d):
    return next(r for r in d["recommendations"] if r["status"] == "proposed")


def test_main_demo_flow(client, approver, operator):
    # 1. A network-timeout event arrives. 2. ResolveOS recommends a retry, needing a human.
    case_id = run("network_timeout", overrides={"merchant": "Acme Retail", "amount_minor": 124000})["case_id"]
    d = detail(client, operator, case_id)
    assert d["case"]["status"] == "awaiting_approval"
    retry = top(d)
    assert retry["action_type"] == "RETRY_CAPTURE" and retry["gate_decision"] == "human_approval"

    # 3. Operator rejects it as too risky. 4. ResolveOS proposes reconcile first.
    r = client.post(f"/api/cases/{case_id}/recommendations/{retry['id']}/reject", headers=operator,
                    json={"reason": "Too risky", "note": "Check the processor first"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["case"]["rejection_count"] == 1
    assert top(d)["action_type"] == "RECONCILE_WITH_PROCESSOR"
    stale_retry = next(x for x in d["recommendations"] if x["action_type"] == "RETRY_CAPTURE")

    # 5. A late-success event arrives. 6. The stale retry is invalidated.
    run("late_success", case_id=case_id)
    d = detail(client, operator, case_id)
    hist = {x["id"]: x for x in d["history"]}
    assert hist[stale_retry["id"]]["status"] == "invalidated"
    assert "charge twice" in hist[stale_retry["id"]]["status_reason"]

    # 7. The final state is re-read and verified (reconcile auto-runs once the processor status is final).
    assert d["case"]["status"] == "resolved", d["case"]
    ex = d["executions"][-1]
    assert ex["verified"] and ex["verification"]["processor_status"] == "captured"
    assert ex["verification"]["ledger_status"] == "captured" and ex["verification"]["captures"] == 1

    # 8. The complete decision sequence is in the replay.
    kinds = [e["kind"] for e in client.get(f"/api/cases/{case_id}/replay", headers=operator).json()]
    for k in ("event", "triage", "evidence", "retrieval", "diagnosis", "risk", "gate", "decision", "invalidation",
              "execution", "verification"):
        assert k in kinds, k


def test_duplicate_event_dropped_and_auto_resolved(client, operator):
    out = run("duplicate_event")
    assert out["duplicate"] is True
    d = detail(client, operator, out["case_id"])
    assert d["case"]["status"] == "resolved" and d["case"]["route"] == "auto_run"
    assert any("Duplicate event" in t["summary"] for t in d["timeline"])


def test_compliance_hold_is_hard_blocked(client, approver, compliance):
    case_id = run("sanctions_hold")["case_id"]
    d = detail(client, compliance, case_id)
    assert d["case"]["route"] == "hard_block"
    assert d["case"]["status"] == "escalated"  # escalation is the only action allowed, and it ran
    assert all(r["action_type"] in ("ESCALATE_TO_COMPLIANCE", "ADD_CASE_NOTE", "REQUEST_MERCHANT_INFO")
               for r in d["recommendations"])


def test_release_hold_never_allowed(client, approver):
    from app.services.safety_gate import GateContext, evaluate
    from app.db import utcnow
    g = evaluate("RELEASE_HOLD", GateContext(now=utcnow(), kill_switch=False, compliance_hold=True, evidence=[],
                                             processor_status="held", ledger_status="none", risk_score=1,
                                             retries_used=0, max_retries=2, has_idempotency_key=True,
                                             evidence_max_age_s=300, risk_auto_max=30,
                                             auto_run_allowlist=["RELEASE_HOLD"]))
    assert g.decision == "hard_block"


def test_operator_cannot_approve_money_movement(client, operator):
    case_id = run("network_timeout")["case_id"]
    rec = top(detail(client, operator, case_id))
    r = client.post(f"/api/cases/{case_id}/recommendations/{rec['id']}/approve", headers=operator)
    assert r.status_code == 403 and r.json()["error"]["code"] == "FORBIDDEN_ROLE"


def test_stale_evidence_blocks_approval(client, approver):
    case_id = run("processor_cutoff")["case_id"]
    rec = top(detail(client, approver, case_id))
    with SessionLocal() as db:  # age the evidence past the freshness window
        for e in db.query(Evidence).filter(Evidence.case_id == case_id):
            e.observed_at = e.observed_at - timedelta(hours=1)
        db.commit()
    r = client.post(f"/api/cases/{case_id}/recommendations/{rec['id']}/approve", headers=approver)
    assert r.status_code == 409 and r.json()["error"]["code"] == "EVIDENCE_STALE"


def test_stale_feed_refresh_then_reconcile(client, operator):
    case_id = run("stale_evidence")["case_id"]
    d = detail(client, operator, case_id)
    assert d["case"]["route"] == "more_evidence"
    d = client.post(f"/api/cases/{case_id}/evidence/refresh", headers=operator).json()
    assert d["case"]["status"] == "resolved", d["case"]


def test_execution_is_exactly_once(client, approver):
    case_id = run("processor_cutoff")["case_id"]
    rec = top(detail(client, approver, case_id))
    assert client.post(f"/api/cases/{case_id}/recommendations/{rec['id']}/approve", headers=approver).status_code == 200
    a = client.post(f"/api/cases/{case_id}/recommendations/{rec['id']}/execute", headers=approver).json()
    b = client.post(f"/api/cases/{case_id}/recommendations/{rec['id']}/execute", headers=approver).json()
    assert a["id"] == b["id"]
    with SessionLocal() as db:
        p = db.get(SimPayment, detail(client, approver, case_id)["case"]["payment_id"])
        assert len([e for e in p.ledger_entries if e["kind"] == "transfer"]) == 1


def test_conflicting_states_block_money_movement():
    from app.services.safety_gate import EvidenceView, GateContext, evaluate
    from app.db import utcnow
    now = utcnow()
    g = evaluate("RETRY_CAPTURE", GateContext(now=now, kill_switch=False, compliance_hold=False,
                                              evidence=[EvidenceView("processor", now), EvidenceView("ledger", now)],
                                              processor_status="failed", ledger_status="captured", risk_score=10,
                                              retries_used=0, max_retries=2, has_idempotency_key=True,
                                              evidence_max_age_s=300, risk_auto_max=30, auto_run_allowlist=[]))
    assert g.decision == "more_evidence"


def test_three_rejections_escalate(client, operator):
    case_id = run("processor_cutoff")["case_id"]
    for _ in range(3):
        d = detail(client, operator, case_id)
        rec = top(d)
        r = client.post(f"/api/cases/{case_id}/recommendations/{rec['id']}/reject", headers=operator,
                        json={"reason": "Wrong cause"})
        assert r.status_code == 200
    d = detail(client, operator, case_id)
    assert d["case"]["status"] == "escalated" and d["case"]["rejection_count"] == 3


def test_kill_switch_blocks_execution(client, admin, approver):
    case_id = run("processor_cutoff")["case_id"]
    rec = top(detail(client, approver, case_id))
    assert client.post("/api/admin/kill-switch", headers=admin, json={"enabled": True, "confirm": "nope"}).status_code == 400
    assert client.post("/api/admin/kill-switch", headers=admin, json={"enabled": True, "confirm": "PAUSE"}).status_code == 200
    r = client.post(f"/api/cases/{case_id}/recommendations/{rec['id']}/approve", headers=approver)
    assert r.status_code == 423
    assert client.post("/api/admin/kill-switch", headers=approver, json={"enabled": False, "confirm": "RESUME"}).status_code == 403


def test_prompt_injection_doc_is_quarantined(client, operator):
    case_id = run("network_timeout", overrides={"merchant": "Acme Retail"})["case_id"]
    d = detail(client, operator, case_id)
    assert any(t["kind"] == "security" and "NOTE-ACME-9" in t["summary"] for t in d["timeline"])
    assert all(r["doc_id"] != "NOTE-ACME-9" for r in d["diagnosis"]["retrieved"])


def test_unauthenticated_requests_rejected(client):
    assert client.get("/api/cases").status_code == 401
