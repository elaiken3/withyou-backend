from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Header, Path

from .. import db
from ..auth import authorize_install
from ..models import INSTALL_ID_PATTERN, PrefsIn

router = APIRouter(prefix="/v1/prefs", tags=["prefs"])


@router.put("/{install_id}")
async def put_prefs(
    install_id: Annotated[str, Path(pattern=INSTALL_ID_PATTERN)],
    payload: PrefsIn,
    x_install_secret: Annotated[str | None, Header()] = None,
):
    await authorize_install(install_id, x_install_secret)

    now = datetime.now(UTC)
    await db.prefs.update_one(
        {"_id": install_id},
        {"$set": {**payload.model_dump(), "updated_at": now}},
        upsert=True,
    )
    return {"ok": True}
