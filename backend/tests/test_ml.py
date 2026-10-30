"""End-to-end checks with the real ML/RAG artifacts (skipped when backend/ml_artifacts is absent)."""

from pathlib import Path

import pytest

from app.config import settings
from app.db import SessionLocal
from app.services import ml, scenarios

ART = Path(settings.ml_artifacts_dir)
pytestmark = pytest.mark.skipif(not (ART / "resolveos_kb.pkl").exists(), reason="ML artifacts not present")


@pytest.fixture(scope="module")
def runtime():
    old = settings.ml_enabled
    settings.ml_enabled = True
    rt = ml.MLRuntime()
    assert rt.load(), rt.error
    saved, ml.runtime = ml.runtime, rt
    yield rt
    settings.ml_enabled = old
    ml.runtime = saved


def run(key, **kw):
    with SessionLocal() as db:
        out = scenarios.run(db, key, **kw)
        db.commit()
        return out


def test_retrieval_is_hybrid_and_filters_background(runtime):
    hits = runtime.retrieve("gateway timeout capture unconfirmed", k=6, exc_type="NETWORK_TIMEOUT")
    assert hits and all(h["retrieval"] == "hybrid" for h in hits)
    assert all(h["type"] != "wikipedia" for h in hits)
    assert any(h["type"] in ("playbook", "runbook", "policy") for h in hits)


def test_triage_matches_notebook_hard_set(runtime):
    import pandas as pd

    d = pd.read_parquet(ART / "hard_set.parquet")
    m = runtime.triage["model"]
    acc = (m.predict(runtime._embed(d.hard_text.tolist())) == d.exc_type).mean()
    assert abs(acc - runtime.metrics["triage_embed_lr_sim_plus_real"]["hard_acc"]) < 0.02


def test_models_feed_the_case(client, approver, operator, runtime):
    case_id = run("network_timeout", overrides={"merchant": "Acme Retail", "amount_minor": 124000})["case_id"]
    d = client.get(f"/api/cases/{case_id}", headers=operator).json()
    assert d["diagnosis"]["ml"]["triage"]["label"] == "NETWORK_TIMEOUT"
    assert d["diagnosis"]["ml"]["action"]["label"]
    assert any(r["retrieval"] == "hybrid" for r in d["diagnosis"]["retrieved"])
    for r in d["recommendations"]:
        assert r["risk_detail"]["scorer"] == "lightgbm-calibrated" and 0 <= r["risk_detail"]["probability"] <= 1
    # A blind retry must score riskier than reconciling first.
    by = {r["action_type"]: r["risk_detail"]["probability"] for r in d["recommendations"]}
    assert by["RETRY_CAPTURE"] > by["RECONCILE_WITH_PROCESSOR"]


def test_demo_flow_still_holds_with_models(client, operator, approver, runtime):
    case_id = run("network_timeout")["case_id"]
    d = client.get(f"/api/cases/{case_id}", headers=operator).json()
    retry = next(r for r in d["recommendations"] if r["status"] == "proposed")
    assert retry["action_type"] == "RETRY_CAPTURE" and retry["gate_decision"] == "human_approval"
    d = client.post(f"/api/cases/{case_id}/recommendations/{retry['id']}/reject", headers=operator,
                    json={"reason": "Too risky"}).json()
    assert next(r for r in d["recommendations"] if r["status"] == "proposed")["action_type"] == "RECONCILE_WITH_PROCESSOR"
    run("late_success", case_id=case_id)
    d = client.get(f"/api/cases/{case_id}", headers=operator).json()
    assert any(r["action_type"] == "RETRY_CAPTURE" and r["status"] == "invalidated" for r in d["history"])
    # The action predictor recognises the situation as "cancel the pending action and verify".
    assert d["diagnosis"]["ml"]["action"]["label"] == "CANCEL_PENDING_AND_VERIFY"
    rec = next(r for r in d["recommendations"] if r["status"] in ("proposed", "executed"))
    assert rec["action_type"] == "RECONCILE_WITH_PROCESSOR"
    assert rec["risk_detail"]["model_action"] == "CANCEL_PENDING_AND_VERIFY"
    if d["case"]["status"] == "awaiting_approval":  # the calibrated model rates this medium risk (p~0.3)
        d = client.post(f"/api/cases/{case_id}/recommendations/{rec['id']}/approve", headers=approver).json()
    assert d["case"]["status"] == "resolved" and d["executions"][-1]["verified"]
    assert d["executions"][-1]["verification"]["captures"] == 1


def test_stale_feed_refresh_with_models(client, operator, runtime):
    case_id = run("stale_evidence")["case_id"]
    d = client.post(f"/api/cases/{case_id}/evidence/refresh", headers=operator).json()
    top = next(r for r in d["recommendations"] if r["status"] == "proposed")
    assert top["action_type"] == "RECONCILE_WITH_PROCESSOR"
    assert d["diagnosis"]["ml"]["action"]["label"] == "RECONCILE_FIRST"
    # Fresh evidence still conflicts on a large amount: the model keeps a person in the loop.
    assert d["case"]["status"] == "awaiting_approval" and top["risk_detail"]["probability"] > 0.2


def test_compliance_hold_still_hard_blocked(client, compliance, runtime):
    d = client.get(f"/api/cases/{run('sanctions_hold')['case_id']}", headers=compliance).json()
    assert d["case"]["route"] == "hard_block" and d["case"]["status"] == "escalated"
