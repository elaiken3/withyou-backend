from fastapi import APIRouter
from datetime import datetime, timezone

from ..models import DeviceRegisterIn
from ..db import installs, devices

router = APIRouter(prefix="/v1/devices", tags=["devices"])


@router.post("/register")
async def register_device(payload: DeviceRegisterIn):
    """
    Registers/updates an install + device token.

    Expect payload to include:
      - install_id (stable UUID per install)
      - device_token (APNs token hex)
      - timezone
      - push_enabled
      - apns_environment: "sandbox" | "production"
        (recommended: send from iOS so backend can route correctly)
    """
    now = datetime.now(timezone.utc)

    await installs.update_one(
        {"_id": payload.install_id},
        {
            "$setOnInsert": {"created_at": now},
            "$set": {
                "timezone": payload.timezone,
                "push_enabled": payload.push_enabled,
                "last_seen_at": now,
                # keep a copy here too so you can route per-install if needed
                "apns_environment": payload.apns_environment,
            },
        },
        upsert=True,
    )

    # Store by token for easy upserts, but include environment so you can filter later.
    await devices.update_one(
        {"_id": payload.device_token},
        {
            "$setOnInsert": {"created_at": now},
            "$set": {
                "install_id": payload.install_id,
                "platform": "ios",
                "updated_at": now,
                "apns_environment": payload.apns_environment,
            },
        },
        upsert=True,
    )

    return {"ok": True}
