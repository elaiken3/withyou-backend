from fastapi import FastAPI
from .routes import devices, prefs, events

app = FastAPI(title="With You Backend")

app.include_router(devices.router)
app.include_router(prefs.router)
app.include_router(events.router)

@app.get("/health")
def health():
    return {"ok": True}
