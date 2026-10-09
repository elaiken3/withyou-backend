import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException

from .. import db
from ..auth import hash_install_secret, install_secret_matches, new_install_secret
from ..models import DeviceRegisterIn

router = APIRouter(prefix="/v1/devices", tags=["devices"])
logger = logging.getLogger("withyou.devices")


@router.post("/register")
async def register_device(
    payload: DeviceRegisterIn,
    x_install_secret: Annotated[str | None, Header()] = None,
):
    """
    Registers/updates an install + device token.

    Expect payload to include:
      - install_id (stable UUID per install)
      - device_token (APNs token hex)
      - timezone (IANA name)
      - push_enabled
      - apns_environment: "sandbox" | "production"
        (recommended: send from iOS so backend can route correctly)

    The first registration of an install returns a one-time ``install_secret``.
    Later calls should send it as ``X-Install-Secret``; a wrong secret is
    rejected (403). Calls without the header are still accepted so existing
    app builds keep working.

    Every response includes ``install_has_secret: true``. An app that holds no
    secret and receives none can tell from this that the secret was issued to
    an earlier build that discarded it; it should then start over with a fresh
    install_id (the server never re-issues a secret for an existing install).
    """
    now = datetime.now(UTC)

    existing = await db.installs.find_one({"_id": payload.install_id}, {"secret_hash": 1})
    stored_hash = (existing or {}).get("secret_hash")
    if stored_hash:
        if x_install_secret is None:
            logger.info("register without X-Install-Secret for an install that has one (older app build)")
        elif not install_secret_matches(x_install_secret, stored_hash):
            raise HTTPException(status_code=403, detail="forbidden")

    await db.installs.update_one(
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
    await db.devices.update_one(
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

    response = {"ok": True, "install_has_secret": True}
    if not stored_hash:
        # Issue a secret only if the install still has none. The filter makes
        # this safe against two concurrent first registrations: only one wins.
        secret = new_install_secret()
        result = await db.installs.update_one(
            {"_id": payload.install_id, "secret_hash": None},
            {"$set": {"secret_hash": hash_install_secret(secret)}},
        )
        if result.modified_count == 1:
            response["install_secret"] = secret
    return response
