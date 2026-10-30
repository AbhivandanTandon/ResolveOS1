# ResolveOS AI

An AI copilot for payment operations. It investigates failed, pending and held payments, gathers evidence,
diagnoses the likely cause and recommends the safest next action. **The LLM recommends; a deterministic
safety gate decides.** Every payment in this repo is simulated.

## Run it

**On Windows, double-click `start.bat`.** The first run installs everything, which takes several minutes. It then starts both servers and opens http://localhost:5173. To stop, close the backend and frontend windows.

To run it by hand:

Backend (Python 3.12, FastAPI). API docs at http://localhost:8000/docs.

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt     # macOS/Linux: .venv/bin/python
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000
```

Frontend (React + Vite + Tailwind, JavaScript). It proxies `/api` and `/ws` to port 8000.

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

Tests: `cd backend && .venv/Scripts/python -m pytest -q`

The first start applies the Alembic migrations, creating `resolveos.db` (SQLite) with 4 demo users, the knowledge base
and 7 seeded cases. Delete the file to reset. For the full stack run `docker compose up -d`, then set in `backend/.env`:

```
DATABASE_URL=postgresql+psycopg://resolveos:resolveos@localhost:5432/resolveos
REDIS_URL=redis://localhost:6379/0
```

Migrations: `.venv/Scripts/python -m alembic upgrade head` (also run automatically on start). After changing
`app/models.py`: `.venv/Scripts/python -m alembic revision --autogenerate -m "describe change"`.

## Main demo (acceptance flow)

1. Sign in as **Anika Rao (approver)** or **Dev Malhotra (operator)**.
2. Open the Acme Retail **network timeout** case. ResolveOS recommends retrying with the original idempotency key and routes it to human approval.
3. **Reject** it as *Too risky*. ResolveOS proposes *Reconcile with Processor A first* and shows the diff from the rejected plan.
4. Click **Send late success event** (or Simulator → Late success). The case updates live over the WebSocket.
5. The stale retry is **invalidated**, the reconcile auto-runs once, and the processor and ledger are re-read and **verified**.
6. **Audit → Replay** steps through every event, retrieval, model output, gate decision, human decision and verification.

## How it works

| Piece | Where |
|---|---|
| Investigation graph (LangGraph): triage → evidence → retrieval → diagnosis → risk → safety gate | `backend/app/services/engine.py` |
| Deterministic safety gate (no model calls) | `backend/app/services/safety_gate.py` |
| Action registry (only these actions exist) | `backend/app/services/actions.py` |
| Nemotron client + strict output schema + deterministic fallback | `backend/app/services/llm.py` |
| BM25 retrieval, optional BGE hybrid, prompt-injection quarantine | `backend/app/services/knowledge.py` |
| Risk score (LightGBM `.joblib` if configured, else heuristic) | `backend/app/services/risk.py` |
| Simulated processor and ledger with idempotency | `backend/app/services/processor.py` |
| Scenarios | `backend/app/services/scenarios.py` |
| Synthetic baseline comparison | `backend/app/services/benchmark.py` |

Routing: **auto-run** only for allowlisted actions that move no money, with fresh and consistent evidence and low risk;
**human approval** for everything else; **more evidence** when processor or ledger data is stale, missing or conflicting;
**hard block** for compliance holds, prohibited actions, exhausted retries and the kill switch. The gate runs when a
plan is created, again at approval and again immediately before execution. Executions are unique per recommendation
(exactly once), and repeat requests return the first result.

Roles are enforced on the server: operators can reject and approve actions that move no money; approvers and admins
can approve money movement; only compliance (or admin) can act on a compliance hold; only admins change policy,
roles or the kill switch (which requires typing PAUSE / RESUME).

## Frontend

Vertical sidebar navigation grouped into Operations, Intelligence and Governance. It collapses to an icon rail on
desktop and becomes a drawer on phones. **⌘K / Ctrl+K** opens a palette that searches pages, cases and knowledge.
The bell in the top bar turns on approval alerts (browser notifications when the tab is in the background).
Keyboard: `A` approve / `R` reject on a case, `J` / `K` / `A` in the Approvals inbox, `/` focuses the case search.

## API additions

`POST /api/cases/{id}/notes` (human notes, read by the agent as untrusted data) · `POST /api/cases/{id}/investigate`
· `GET /api/audit/export?format=csv|json` · `POST/DELETE /api/knowledge` (only admin/compliance can mark a document
trusted; instruction-like text is refused as trusted and quarantined at retrieval) · `POST /api/admin/users`,
`PUT /api/admin/users/{id}/active` · `GET /api/health` (database, live-update backend, model, risk scorer, retrieval).
Full list at `/docs`.

Scenarios: network timeout, duplicate event, late success, sanctions hold, processor cut-off, stale evidence,
conflicting states (ledger shows a capture the processor rejected), returned transfer, chargeback without an order,
issuer decline.

## What is real and what is simulated

- **Simulated:** the processor, ledger, bank rail, screening provider, merchants and all payments.
- **Cost per case:** tokens are metered from every model call. A dollar figure appears only if you set
  `LLM_PRICE_PER_MTOK` to your contract prices; nothing is invented.
- **Without `NVIDIA_API_KEY`:** diagnoses come from a deterministic rule-based fallback and are labelled
  `deterministic-fallback` in the UI and audit trail. With a key, Nemotron Ultra/Super are called and their output is
  validated against a strict schema; invalid output falls back and is logged.
- **Models:** trained on the notebook's synthetic simulator data, plus Banking77/CFPB text with Nemotron-made labels.
  Their metrics are offline results, not production accuracy.
- **Metrics → Measured:** computed from the cases in the database. **Metrics → Baselines:** a synthetic suite of 10
  scenario contexts, clearly labelled; not a measurement on real traffic.

## ML / RAG models (from the notebook export)

`backend/ml_artifacts/` holds the notebook export (unzipped from `resolveos_ml_export (2).zip`). On start the API comes
up immediately and a background thread loads the models (about 15 s once BGE is cached; the first run downloads
`BAAI/bge-small-en-v1.5`, about 130 MB). `GET /api/health` reports `ml.state`: `loading`, `ready` or `unavailable`.
Until it's ready, or if loading fails, the app falls back to BM25 and the heuristic risk score and labels that in
the audit trail.

| Artifact | Used for | Where |
|---|---|---|
| `resolveos_kb.pkl` + vendored `resolveos_retriever.py` | Hybrid RAG (BGE + TF-IDF, reciprocal-rank fusion) over 2,414 chunks, fused with ResolveOS's own documents. Operational search excludes Wikipedia and raw customer text. The KB's safety invariants go into the Nemotron system prompt. | `services/kb_retriever.py`, `services/knowledge.py` |
| `triage_model.joblib` | Second-opinion exception classification (unprefixed BGE embeddings, reproduces the notebook's hard-set accuracy of 0.769). Used as the label only when the rules can't classify an event. | `services/ml.py`, triage node |
| `action_model.joblib` | Second-opinion next action, shown on the case and passed to Nemotron as advisory context | diagnose node |
| `risk_model.joblib` (+ isotonic calibrator) | Calibrated risk probability for **each** proposed action (the model takes the action as an input) | risk node |
| `cases.parquet` | Rail medians for `amount_rel`, and per-exception medians for inputs ResolveOS doesn't track | `MLRuntime.features` |
| `metrics.json` | Metrics → Models (offline evaluation, clearly labelled) | `/api/metrics` → `offline_eval` |

**Translation layer.** The notebook's vocabulary is mapped in `services/ml.py`: exception types, processor and ledger
states, rails (Processor A → CARD, Processor B → SWIFT, bank rail by currency) and action labels. After a late
success, "reconcile" maps to `CANCEL_PENDING_AND_VERIFY`. `balance_ratio` and `minutes_to_cutoff` use training-set
medians, and each case lists which inputs were defaulted.

**Risk scale.** The calibrated probability is stored as `risk_detail.probability`. The 0–100 score maps the model's
own cut-offs (0.2 / 0.5) onto ResolveOS's low/medium/high boundaries (35 / 75), so the gate's auto-run limit of 30
means p < 0.17. With the real model, a few actions that used to auto-run now need one approval, because the model
rates them as medium risk (for example, reconciling after a late success, p ≈ 0.3). An admin can raise the limit.

None of the models can authorize an action. They feed the diagnosis and the risk score, and the deterministic gate
still decides.

`tests/test_ml.py` runs the real artifacts (skipped if they're missing). The other tests run with `ML_ENABLED=false`.

## Still needs your input

- **NVIDIA API key** for real Nemotron diagnoses.
- Web push to a closed browser (needs VAPID keys and a service worker); in-browser alerts work today.
