from __future__ import annotations

import time
from typing import Optional, Dict, Any

import httpx
import jwt  # PyJWT

from ..config import settings


_client: Optional[httpx.Client] = None
_cached_jwt: Optional[str] = None
_cached_jwt_exp: int = 0  # unix seconds


def apns_configured() -> bool:
    return all(
        [
            settings.apns_team_id,
            settings.apns_key_id,
            settings.apns_auth_key_path,
            settings.apns_topic,
        ]
    )


def _apns_base_url() -> str:
    return "https://api.sandbox.push.apple.com" if settings.apns_use_sandbox else "https://api.push.apple.com"


def _get_http2_client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(http2=True, timeout=httpx.Timeout(10.0, connect=10.0))
    return _client


def close_client() -> None:
    """Optional: call on graceful shutdown."""
    global _client
    if _client is not None:
        _client.close()
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


def send_alert(
    device_token: str,
    title: str,
    body: str,
    badge: int | None = None,
    deep_link: str | None = None,
) -> None:
    if not apns_configured():
        print("[APNS NOT CONFIGURED] Would have sent:", title, body)
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

    url = f"{_apns_base_url()}/3/device/{device_token}"

    headers = {
        "authorization": f"bearer {auth}",
        "apns-topic": settings.apns_topic,
        "apns-push-type": "alert",
        "apns-priority": "10",
        "apns-expiration": "0",
        "content-type": "application/json",
    }

    r = client.post(url, headers=headers, json=payload)

    if r.status_code != 200:
        try:
            detail = r.json()
        except Exception:
            detail = {"body": r.text}

        apns_id = r.headers.get("apns-id")
        raise RuntimeError(f"APNs send failed: {r.status_code} apns-id={apns_id} detail={detail}")
