from fastapi import APIRouter
from datetime import timezone
from dateutil import parser
from ..models import EventIn
from ..db import events_daily
from ..services.events import build_daily_event_update

router = APIRouter(prefix="/v1/events", tags=["events"])

@router.post("")
async def post_event(payload: EventIn):
    ts = parser.isoparse(payload.ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_utc = ts.astimezone(timezone.utc)

    doc_id, update = build_daily_event_update(
        install_id=payload.install_id,
        event_type=payload.event_type,
        ts_utc=ts_utc,
        meta=payload.meta,
    )

    await events_daily.update_one({"_id": doc_id}, update, upsert=True)
    return {"ok": True}
