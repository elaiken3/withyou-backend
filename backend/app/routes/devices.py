from fastapi import APIRouter
from datetime import datetime, timezone
from ..models import DeviceRegisterIn
from ..db import installs, devices

router = APIRouter(prefix="/v1/devices", tags=["devices"])

@router.post("/register")
async def register_device(payload: DeviceRegisterIn):
    now = datetime.now(timezone.utc)

    await installs.update_one(
        {"_id": payload.install_id},
        {"$setOnInsert": {"created_at": now},
         "$set": {"timezone": payload.timezone,
                  "push_enabled": payload.push_enabled,
                  "last_seen_at": now}},
        upsert=True
    )

    # device_token is unique; store it as _id for easy upserts
    await devices.update_one(
        {"_id": payload.device_token},
        {"$set": {"install_id": payload.install_id,
                  "platform": "ios",
                  "updated_at": now}},
        upsert=True
    )

    return {"ok": True}
