from fastapi import APIRouter
from datetime import datetime, timezone
from ..models import PrefsIn
from ..db import prefs

router = APIRouter(prefix="/v1/prefs", tags=["prefs"])

@router.put("/{install_id}")
async def put_prefs(install_id: str, payload: PrefsIn):
    now = datetime.now(timezone.utc)
    await prefs.update_one(
        {"_id": install_id},
        {"$set": {**payload.model_dump(), "updated_at": now}},
        upsert=True
    )
    return {"ok": True}
