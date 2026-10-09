from typing import Annotated

from fastapi import APIRouter, Header, Path

from .. import db
from ..auth import authorize_install
from ..models import INSTALL_ID_PATTERN

router = APIRouter(prefix="/v1/installs", tags=["installs"])


@router.delete("/{install_id}")
async def delete_install(
    install_id: Annotated[str, Path(pattern=INSTALL_ID_PATTERN)],
    x_install_secret: Annotated[str | None, Header()] = None,
):
    """Delete everything stored for this install (user-controlled deletion)."""
    await authorize_install(install_id, x_install_secret)

    await db.devices.delete_many({"install_id": install_id})
    await db.prefs.delete_one({"_id": install_id})
    await db.events_daily.delete_many({"install_id": install_id})
    await db.push_log.delete_many({"install_id": install_id})
    # Install doc last: if anything above fails, a retry can still authorize.
    await db.installs.delete_one({"_id": install_id})
    return {"ok": True}
