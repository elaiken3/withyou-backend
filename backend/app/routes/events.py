from fastapi import APIRouter
from datetime import datetime, timezone
from dateutil import parser
from ..models import EventIn
from ..db import events_daily

router = APIRouter(prefix="/v1/events", tags=["events"])

@router.post("")
async def post_event(payload: EventIn):
    ts = parser.isoparse(payload.ts)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    ts_utc = ts.astimezone(timezone.utc)
    day = ts_utc.date().isoformat()  # "YYYY-MM-DD"

    doc_id = f"{payload.install_id}|{day}"
    update = {"$setOnInsert": {"install_id": payload.install_id, "date": day},
              "$set": {"updated_at": datetime.now(timezone.utc)}}

    # Minimal event handling
    if payload.event_type == "capture_added":
        inc = int((payload.meta or {}).get("count", 1))
        update["$inc"] = {"captures_count": inc}
    elif payload.event_type == "refocus_opened":
        update["$inc"] = {"refocus_opens_count": 1}
    elif payload.event_type == "focus_session_started":
        update["$set"]["focus_started_at"] = ts_utc
        # reset assumption
        update["$set"]["focus_first_step_set"] = bool((payload.meta or {}).get("has_first_step", False))
    elif payload.event_type == "focus_first_step_set":
        update["$set"]["focus_first_step_set"] = True
        update["$set"]["focus_first_step_set_at"] = ts_utc

    await events_daily.update_one({"_id": doc_id}, update, upsert=True)
    return {"ok": True}
