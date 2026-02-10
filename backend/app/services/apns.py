from __future__ import annotations

import logging
import time
from typing import Optional, Dict, Any

import httpx
import jwt  # PyJWT

from ..config import settings


class APNSTokenInvalid(RuntimeError):
    def __init__(self, status_code: int, reason: str | None):
        super().__init__(f"APNs token invalid: status={status_code} reason={reason}")
        self.status_code = status_code
        self.reason = reason


_client: Optional[httpx.AsyncClient] = None
_cached_jwt: Optional[str] = None
_cached_jwt_exp: int = 0  # unix seconds
logger = logging.getLogger("withyou.apns")


def apns_configured() -> bool:
    return all(
        [
            settings.apns_team_id,
            settings.apns_key_id,
            settings.apns_auth_key_path,
            settings.apns_topic,
        ]
    )


def _apns_base_url(apns_environment: Optional[str]) -> str:
    if apns_environment == "sandbox":
        use_sandbox = True
    elif apns_environment == "production":
        use_sandbox = False
    else:
        use_sandbox = settings.apns_use_sandbox
    return "https://api.sandbox.push.apple.com" if use_sandbox else "https://api.push.apple.com"


def _get_http2_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(http2=True, timeout=httpx.Timeout(10.0, connect=10.0))
    return _client


async def close_client() -> None:
    """Optional: call on graceful shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _get_apns_jwt() -> str:
    """
    APNs token-based auth requires a JWT signed with your .p8 private key.
    Token is typically reused for up to 60 minutes; we cache for 50 minutes.
    """
    global _cached_jwt, _cached_jwt_exp

    now = int(time.time())

    if _cached_jwt and now < _cached_jwt_exp:
        return _cached_jwt

    headers = {"alg": "ES256", "kid": settings.apns_key_id}
    claims = {"iss": settings.apns_team_id, "iat": now}

    with open(settings.apns_auth_key_path, "r", encoding="utf-8") as f:
        private_key = f.read()

    token = jwt.encode(
        payload=claims,
        key=private_key,
        algorithm="ES256",
        headers=headers,
    )

    # Normalize bytes -> str (PyJWT version dependent)
    if isinstance(token, bytes):
        token = token.decode("utf-8")

    _cached_jwt = token
    _cached_jwt_exp = now + (50 * 60)
    return token


async def send_alert(
    device_token: str,
    title: str,
    body: str,
    badge: int | None = None,
    deep_link: str | None = None,
    apns_environment: Optional[str] = None,
) -> None:
    if not apns_configured():
        logger.info("[APNS NOT CONFIGURED] Would have sent: %s %s", title, body)
        return

    auth = _get_apns_jwt()
    client = _get_http2_client()

    payload: Dict[str, Any] = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
        }
    }
    if badge is not None:
        payload["aps"]["badge"] = badge
    if deep_link:
        payload["deep_link"] = deep_link

    url = f"{_apns_base_url(apns_environment)}/3/device/{device_token}"

    headers = {
        "authorization": f"bearer {auth}",
        "apns-topic": settings.apns_topic,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-expiration": "0",
        "content-type": "application/json",
    }

    r = await client.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = {"body": r.text}

        apns_id = r.headers.get("apns-id")
        reason = None
        if isinstance(detail, dict):
            reason = detail.get("reason")
        if r.status_code in (400, 410) and reason in {"BadDeviceToken", "Unregistered", "DeviceTokenNotForTopic"}:
            raise APNSTokenInvalid(r.status_code, reason)
        raise RuntimeError(f"APNs send failed: {r.status_code} apns-id={apns_id} detail={detail}")
