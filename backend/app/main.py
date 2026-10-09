import logging
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from . import db
from .auth import api_key_matches
from .config import settings
from .routes import devices, events, installs, prefs
from .services.apns import close_client
from .services.timeutils import as_utc

logger = logging.getLogger("withyou.api")

# /ready fails when the worker's last tick is older than this many intervals.
HEARTBEAT_MAX_AGE_INTERVALS = 3


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    try:
        await db.ensure_indexes()
    except Exception:
        logging.getLogger("withyou.startup").exception("Mongo unavailable during startup; skipping ensure_indexes")
    yield
    await close_client()


app = FastAPI(title="With You Backend", lifespan=lifespan)

app.include_router(devices.router)
app.include_router(prefs.router)
app.include_router(events.router)
app.include_router(installs.router)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path.startswith("/v1/") and not api_key_matches(request.headers.get("X-API-Key")):
        return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)


@app.get("/health")
def health():
    """Liveness: the process is up. Does not touch Mongo."""
    return {"ok": True}


@app.get("/ready")
async def ready():
    """Readiness: Mongo answers and the worker has ticked recently."""
    try:
        await db.database.command("ping")
        heartbeat = await db.worker_heartbeat.find_one({"_id": "scheduler"})
    except Exception:
        logger.warning("readiness check: Mongo unavailable", exc_info=True)
        return JSONResponse(status_code=503, content={"ok": False, "reason": "mongo unavailable"})

    last_tick_at = (heartbeat or {}).get("last_tick_at")
    if not isinstance(last_tick_at, datetime):
        return JSONResponse(status_code=503, content={"ok": False, "reason": "no worker heartbeat"})

    max_age = timedelta(seconds=HEARTBEAT_MAX_AGE_INTERVALS * settings.scheduler_interval_seconds)
    if datetime.now(UTC) - as_utc(last_tick_at) > max_age:
        return JSONResponse(status_code=503, content={"ok": False, "reason": "worker heartbeat stale"})

    return {"ok": True}
