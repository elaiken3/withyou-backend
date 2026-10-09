"""API key and per-install secret checks.

Each install gets a random secret the first time it registers. Only a SHA-256
hash of it is stored. Requests that change or delete an install's data must
present the secret in the ``X-Install-Secret`` header.
"""

import hashlib
import secrets
from typing import Any

from fastapi import HTTPException

from . import db
from .config import settings

INSTALL_SECRET_HEADER = "X-Install-Secret"


def api_key_matches(provided: str | None) -> bool:
    """True when no API key is configured, or the provided key matches it."""
    if not settings.api_key:
        return True
    if provided is None:
        return False
    return secrets.compare_digest(provided.encode("utf-8"), settings.api_key.encode("utf-8"))


def new_install_secret() -> str:
    return secrets.token_urlsafe(32)


def hash_install_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def install_secret_matches(provided: str, stored_hash: str) -> bool:
    return secrets.compare_digest(hash_install_secret(provided), stored_hash)


async def authorize_install(install_id: str, provided_secret: str | None) -> dict[str, Any]:
    """Load an install and check the caller's secret.

    401 if the header is missing, 404 if the install is unknown, 403 if the
    install has no secret yet (it must register first) or the secret is wrong.
    """
    if not provided_secret:
        raise HTTPException(status_code=401, detail="missing install secret")

    inst = await db.installs.find_one({"_id": install_id})
    if inst is None:
        raise HTTPException(status_code=404, detail="unknown install")

    stored_hash = inst.get("secret_hash")
    if not stored_hash or not install_secret_matches(provided_secret, stored_hash):
        raise HTTPException(status_code=403, detail="forbidden")

    return inst
