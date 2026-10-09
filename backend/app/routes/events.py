from typing import Annotated

from fastapi import APIRouter, Header

from .. import db
from ..auth import authorize_install
from ..models import EventIn
from ..services.defaults import DEFAULT_TIMEZONE
from ..services.events import build_daily_event_update
from ..services.timeutils import local_day, zone_or_utc

router = APIRouter(prefix="/v1/events", tags=["events"])


@router.post("")
async def post_event(
    payload: EventIn,
    x_install_secret: Annotated[str | None, Header()] = None,
):
    inst = await authorize_install(payload.install_id, x_install_secret)

    # Roll up by the install's local date, matching the scheduler's "today".
    tz = zone_or_utc(inst.get("timezone") or DEFAULT_TIMEZONE)
    doc_id, update = build_daily_event_update(
        install_id=payload.install_id,
        event_type=payload.event_type,
        ts_utc=payload.ts,
        day=local_day(payload.ts, tz),
        meta=payload.meta.model_dump(exclude_none=True) if payload.meta else None,
    )

    await db.events_daily.update_one({"_id": doc_id}, update, upsert=True)
    return {"ok": True}
