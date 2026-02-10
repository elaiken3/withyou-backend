import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from .routes import devices, prefs, events
from .db import ensure_indexes
from .config import settings

app = FastAPI(title="With You Backend")

app.include_router(devices.router)
app.include_router(prefs.router)
app.include_router(events.router)

@app.on_event("startup")
async def startup():
    if not logging.getLogger().handlers:
        logging.basicConfig(level=logging.INFO)
    await ensure_indexes()


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if settings.api_key and request.url.path.startswith("/v1/"):
        key = request.headers.get("X-API-Key")
        if key != settings.api_key:
            return JSONResponse(status_code=401, content={"detail": "unauthorized"})
    return await call_next(request)

@app.get("/health")
def health():
    return {"ok": True}
