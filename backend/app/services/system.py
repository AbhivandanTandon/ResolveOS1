"""System configuration, audit trail and live-update broadcasting."""

import asyncio
import json
import logging
import threading

from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import AuditEvent, SystemConfig

log = logging.getLogger("resolveos")

DEFAULT_CONFIG = {
    "kill_switch": False,
    "evidence_max_age_s": 300,
    "risk_auto_max": 30,
    "max_retries": 2,
    "max_rejections": 3,
    # REFRESH_EVIDENCE is eligible but off by default so stale cases visibly wait for "More evidence".
    "auto_run_allowlist": [
        "DROP_DUPLICATE_EVENT",
        "RECONCILE_WITH_PROCESSOR",
        "ESCALATE_TO_COMPLIANCE",
        "NOTIFY_CUSTOMER",
    ],
}


def get_config(db: Session) -> dict:
    rows = {r.key: r.value for r in db.scalars(select(SystemConfig))}
    return {k: rows.get(k, v) for k, v in DEFAULT_CONFIG.items()}


def set_config(db: Session, key: str, value, actor: str) -> None:
    row = db.get(SystemConfig, key)
    if row is None:
        db.add(SystemConfig(key=key, value=value, updated_by=actor))
    else:
        row.value = value
        row.updated_by = actor
        row.updated_at = utcnow()


def audit(db: Session, case_id: str | None, kind: str, actor: str, summary: str,
          tool: str | None = None, data: dict | None = None) -> AuditEvent:
    ev = AuditEvent(case_id=case_id, kind=kind, actor=actor, tool=tool, summary=summary, data=data or {},
                    created_at=utcnow())
    db.add(ev)
    db.flush()
    hub.publish("audit", case_id=case_id, kind=kind, actor=actor, tool=tool, summary=summary)
    return ev


class LiveHub:
    """Fan-out of change notifications over WebSockets. Safe to call from worker threads."""

    def __init__(self):
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop

    async def connect(self, ws: WebSocket):
        await ws.accept()
        with self._lock:
            self._clients.add(ws)

    def disconnect(self, ws: WebSocket):
        with self._lock:
            self._clients.discard(ws)

    async def _send_all(self, message: str):
        with self._lock:
            clients = list(self._clients)
        for ws in clients:
            try:
                await ws.send_text(message)
            except Exception:
                self.disconnect(ws)

    # ---- Redis fan-out: every worker publishes to one channel and relays it to its own sockets.
    CHANNEL = "resolveos:live"
    _redis = None

    def use_redis(self, url: str | None) -> bool:
        if not url:
            return False
        try:
            import redis

            client = redis.Redis.from_url(url, socket_connect_timeout=2)
            client.ping()
            self._redis = client
            log.info("live updates fan out through Redis")
            return True
        except Exception as e:
            log.warning("Redis unavailable (%s); live updates stay in-process", e)
            return False

    @property
    def backend(self) -> str:
        return "redis" if self._redis is not None else "in-process"

    async def relay_from_redis(self, url: str):
        import redis.asyncio as aredis

        sub = aredis.Redis.from_url(url).pubsub()
        await sub.subscribe(self.CHANNEL)
        async for item in sub.listen():
            if item.get("type") == "message":
                data = item["data"]
                await self._send_all(data.decode() if isinstance(data, bytes) else data)

    def publish(self, type_: str, **payload):
        msg = json.dumps({"type": type_, "at": utcnow().isoformat() + "Z", **payload}, default=str)
        if self._redis is not None:
            try:
                self._redis.publish(self.CHANNEL, msg)
                return
            except Exception as e:  # fall back to local delivery if Redis drops
                log.warning("Redis publish failed: %s", e)
        if self._loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send_all(msg), self._loop)
        except RuntimeError:
            log.debug("live hub loop closed")


hub = LiveHub()
