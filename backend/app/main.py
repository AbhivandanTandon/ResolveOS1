import asyncio
import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect, select, text

from .config import settings
from .db import Base, SessionLocal, engine
from .models import PaymentCase, User
from .routers import cases, ops, platform
from .services import knowledge, ml, scenarios
from .services.engine import EngineError
from .services.system import hub

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

DEMO_USERS = [
    ("anika.rao@example.com", "Anika Rao", "approver"),
    ("dev.malhotra@example.com", "Dev Malhotra", "operator"),
    ("priya.nair@example.com", "Priya Nair", "compliance"),
    ("sam.iyer@example.com", "Sam Iyer", "admin"),
]


def migrate() -> None:
    """Apply Alembic migrations (or create_all when migrations are turned off, e.g. in tests)."""
    if not settings.migrate_on_start:
        Base.metadata.create_all(engine)
        return
    from alembic import command
    from alembic.config import Config

    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as conn:
        cfg.attributes["connection"] = conn
        if "users" in tables and "alembic_version" not in tables:
            # Database created before migrations existed: adopt it at the first revision.
            command.stamp(cfg, "0001")
        command.upgrade(cfg, "head")


def init_db() -> bool:
    migrate()
    with SessionLocal() as db:
        if not db.scalar(select(User.id).limit(1)):
            db.add_all([User(email=e, name=n, role=r) for e, n, r in DEMO_USERS])
        knowledge.seed_knowledge(db)
        db.commit()
        # Decide before the API accepts requests: scenarios run while models load must not cancel seeding.
        return settings.seed_demo and not db.scalar(select(PaymentCase.id).limit(1))


def warm_up(seed: bool) -> None:
    """Load the ML/RAG artifacts (BGE, LightGBM, KB), then seed demo cases so they use the real models.
    Runs in a background thread so the API is reachable while models load."""
    ml.runtime.load()
    if seed:
        with SessionLocal() as db:
            scenarios.seed_demo(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    hub.bind_loop(asyncio.get_running_loop())
    relay = None
    if hub.use_redis(settings.redis_url):
        relay = asyncio.create_task(hub.relay_from_redis(settings.redis_url))
    seed = await asyncio.to_thread(init_db)
    threading.Thread(target=warm_up, args=(seed,), name="ml-warm-up", daemon=True).start()
    yield
    if relay:
        relay.cancel()


app = FastAPI(
    title="ResolveOS AI",
    version="0.2.0",
    description="Evidence-driven payment resolution with a deterministic safety gate, human oversight and a full "
                "audit trail. All payments are simulated.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


def _err(status: int, code: str, message: str, detail: dict | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, **(detail or {})}})


@app.exception_handler(EngineError)
async def engine_error(_: Request, e: EngineError):
    return _err(e.status, e.code, e.message, e.detail)


@app.exception_handler(HTTPException)
async def http_error(_: Request, e: HTTPException):
    if isinstance(e.detail, dict):
        return _err(e.status_code, e.detail.get("code", "ERROR"), e.detail.get("message", ""))
    return _err(e.status_code, "ERROR", str(e.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, e: RequestValidationError):
    return _err(422, "VALIDATION", "Request is not valid.", {"fields": [
        {"loc": list(x["loc"]), "msg": x["msg"]} for x in e.errors()]})


app.include_router(platform.router)
app.include_router(cases.router)
app.include_router(ops.router)


@app.get("/api/health", tags=["system"], summary="Component status")
def health():
    from .services import llm

    db_ok = True
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "ok": db_ok,
        "database": engine.dialect.name,
        "live_updates": hub.backend,
        "llm": "nvidia" if llm.llm_enabled() else "deterministic-fallback",
        "risk_scorer": "lightgbm-calibrated" if ml.runtime.ready else "heuristic-v1",
        "retrieval": "hybrid BGE + TF-IDF (RRF)" if ml.runtime.ready else "bm25",
        "ml": {"state": "ready" if ml.runtime.ready else "loading" if not ml.runtime.loaded else "unavailable",
               **ml.runtime.status()},
        "simulated_payments": True,
    }


@app.websocket("/ws")
async def ws(socket: WebSocket):
    await hub.connect(socket)
    try:
        while True:
            await socket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(socket)
