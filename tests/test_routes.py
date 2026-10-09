import asyncio
import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from backend.app import main
from backend.app.config import settings

INSTALL_ID = "install-0001"
OTHER_ID = "install-0002"
TOKEN = "ab" * 32
OTHER_TOKEN = "cd" * 32


def run(coro):
    return asyncio.run(coro)


def register(client, install_id=INSTALL_ID, token=TOKEN, headers=None, **overrides):
    body = {
        "install_id": install_id,
        "device_token": token,
        "timezone": "America/New_York",
        "push_enabled": True,
    }
    body.update(overrides)
    return client.post("/v1/devices/register", json=body, headers=headers or {})


def registered_secret(client, install_id=INSTALL_ID, token=TOKEN):
    r = register(client, install_id=install_id, token=token)
    assert r.status_code == 200
    return r.json()["install_secret"]


# --- register ------------------------------------------------------------------


def test_register_issues_secret_once_and_stores_only_hash(client, fake_db):
    r1 = register(client)
    assert r1.status_code == 200
    body = r1.json()
    assert body["ok"] is True
    secret = body["install_secret"]
    assert len(secret) >= 32

    inst = run(fake_db.installs.find_one({"_id": INSTALL_ID}))
    assert inst["secret_hash"] == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in str(inst)

    # Later registrations never return a secret again.
    r2 = register(client, headers={"X-Install-Secret": secret})
    assert r2.status_code == 200
    assert r2.json() == {"ok": True, "install_has_secret": True}

    # Missing header is still accepted (older app builds), without a new secret.
    r3 = register(client)
    assert r3.status_code == 200
    assert r3.json() == {"ok": True, "install_has_secret": True}
    inst = run(fake_db.installs.find_one({"_id": INSTALL_ID}))
    assert inst["secret_hash"] == hashlib.sha256(secret.encode()).hexdigest()


def test_register_with_wrong_secret_is_rejected_without_changes(client, fake_db):
    registered_secret(client)
    r = register(client, token=OTHER_TOKEN, timezone="Europe/Paris", headers={"X-Install-Secret": "wrong"})
    assert r.status_code == 403

    inst = run(fake_db.installs.find_one({"_id": INSTALL_ID}))
    assert inst["timezone"] == "America/New_York"
    assert run(fake_db.devices.find_one({"_id": OTHER_TOKEN})) is None


def test_register_issues_secret_to_existing_install_without_one(client, fake_db):
    run(fake_db.installs.insert_one({"_id": INSTALL_ID, "timezone": "UTC", "push_enabled": True}))
    r = register(client)
    assert r.status_code == 200
    assert "install_secret" in r.json()


def test_register_stores_install_and_device(client, fake_db):
    register(client, apns_environment="production")
    inst = run(fake_db.installs.find_one({"_id": INSTALL_ID}))
    dev = run(fake_db.devices.find_one({"_id": TOKEN}))
    assert inst["timezone"] == "America/New_York"
    assert inst["push_enabled"] is True
    assert dev["install_id"] == INSTALL_ID
    assert dev["apns_environment"] == "production"


# --- prefs ---------------------------------------------------------------------


def test_prefs_require_install_secret(client, fake_db):
    secret = registered_secret(client)
    body = {"max_push_per_day": 1, "daily_checkin": {"enabled": True, "time": "20:00"}}

    assert client.put(f"/v1/prefs/{INSTALL_ID}", json=body).status_code == 401
    assert client.put(f"/v1/prefs/{INSTALL_ID}", json=body, headers={"X-Install-Secret": "nope"}).status_code == 403
    assert run(fake_db.prefs.find_one({"_id": INSTALL_ID})) is None

    r = client.put(f"/v1/prefs/{INSTALL_ID}", json=body, headers={"X-Install-Secret": secret})
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    saved = run(fake_db.prefs.find_one({"_id": INSTALL_ID}))
    assert saved["max_push_per_day"] == 1
    assert saved["daily_checkin"] == {"enabled": True, "time": "20:00"}
    assert saved["focus_nudges"] == {"enabled": False}


def test_prefs_unknown_install_is_404(client):
    r = client.put(f"/v1/prefs/{OTHER_ID}", json={}, headers={"X-Install-Secret": "whatever"})
    assert r.status_code == 404


def test_prefs_install_without_secret_is_403(client, fake_db):
    run(fake_db.installs.insert_one({"_id": INSTALL_ID, "timezone": "UTC", "push_enabled": True}))
    r = client.put(f"/v1/prefs/{INSTALL_ID}", json={}, headers={"X-Install-Secret": "whatever"})
    assert r.status_code == 403


# --- events --------------------------------------------------------------------


def test_events_require_install_secret(client, fake_db):
    secret = registered_secret(client)
    body = {"install_id": INSTALL_ID, "event_type": "refocus_opened", "ts": "2026-02-10T12:00:00Z"}

    assert client.post("/v1/events", json=body).status_code == 401
    assert client.post("/v1/events", json=body, headers={"X-Install-Secret": "nope"}).status_code == 403
    other = {**body, "install_id": OTHER_ID}
    assert client.post("/v1/events", json=other, headers={"X-Install-Secret": secret}).status_code == 404
    assert run(fake_db.events_daily.count_documents({})) == 0

    r = client.post("/v1/events", json=body, headers={"X-Install-Secret": secret})
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_events_roll_up_by_install_local_day(client, fake_db):
    secret = registered_secret(client)  # America/New_York
    headers = {"X-Install-Secret": secret}
    # 02:00 UTC on Feb 10 is 21:00 on Feb 9 in New York.
    body = {"install_id": INSTALL_ID, "event_type": "capture_added", "ts": "2026-02-10T02:00:00Z", "meta": {"count": 3}}
    assert client.post("/v1/events", json=body, headers=headers).status_code == 200
    assert client.post("/v1/events", json=body, headers=headers).status_code == 200

    doc = run(fake_db.events_daily.find_one({"_id": f"{INSTALL_ID}|2026-02-09"}))
    assert doc is not None
    assert doc["date"] == "2026-02-09"
    assert doc["captures_count"] == 6
    assert run(fake_db.events_daily.find_one({"_id": f"{INSTALL_ID}|2026-02-10"})) is None


# --- delete --------------------------------------------------------------------


def _seed_everything(fake_db, install_id, token):
    run(fake_db.prefs.insert_one({"_id": install_id, "max_push_per_day": 2}))
    run(fake_db.devices.insert_one({"_id": token + "ff", "install_id": install_id}))
    run(fake_db.events_daily.insert_one({"_id": f"{install_id}|2026-02-09", "install_id": install_id}))
    run(fake_db.events_daily.insert_one({"_id": f"{install_id}|2026-02-10", "install_id": install_id}))
    run(fake_db.push_log.insert_one({"_id": f"{install_id}|2026-02-09|daily_checkin", "install_id": install_id}))


def test_delete_install_removes_everything(client, fake_db):
    secret = registered_secret(client)
    registered_secret(client, install_id=OTHER_ID, token=OTHER_TOKEN)
    _seed_everything(fake_db, INSTALL_ID, TOKEN)
    _seed_everything(fake_db, OTHER_ID, OTHER_TOKEN)

    r = client.delete(f"/v1/installs/{INSTALL_ID}", headers={"X-Install-Secret": secret})
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    assert run(fake_db.installs.find_one({"_id": INSTALL_ID})) is None
    assert run(fake_db.prefs.find_one({"_id": INSTALL_ID})) is None
    assert run(fake_db.devices.count_documents({"install_id": INSTALL_ID})) == 0
    assert run(fake_db.events_daily.count_documents({"install_id": INSTALL_ID})) == 0
    assert run(fake_db.push_log.count_documents({"install_id": INSTALL_ID})) == 0

    # The other install is untouched.
    assert run(fake_db.installs.find_one({"_id": OTHER_ID})) is not None
    assert run(fake_db.prefs.find_one({"_id": OTHER_ID})) is not None
    assert run(fake_db.devices.count_documents({"install_id": OTHER_ID})) == 2
    assert run(fake_db.events_daily.count_documents({"install_id": OTHER_ID})) == 2
    assert run(fake_db.push_log.count_documents({"install_id": OTHER_ID})) == 1

    # Gone now.
    r = client.delete(f"/v1/installs/{INSTALL_ID}", headers={"X-Install-Secret": secret})
    assert r.status_code == 404


def test_delete_install_requires_secret(client, fake_db):
    registered_secret(client)
    assert client.delete(f"/v1/installs/{INSTALL_ID}").status_code == 401
    assert client.delete(f"/v1/installs/{INSTALL_ID}", headers={"X-Install-Secret": "nope"}).status_code == 403
    assert run(fake_db.installs.find_one({"_id": INSTALL_ID})) is not None


def test_delete_unknown_install_is_404(client):
    assert client.delete(f"/v1/installs/{OTHER_ID}", headers={"X-Install-Secret": "x"}).status_code == 404


def test_reregister_after_delete_issues_new_secret(client):
    secret = registered_secret(client)
    client.delete(f"/v1/installs/{INSTALL_ID}", headers={"X-Install-Secret": secret})
    r = register(client, headers={"X-Install-Secret": secret})
    assert r.status_code == 200
    new_secret = r.json()["install_secret"]
    assert new_secret != secret


# --- API key -------------------------------------------------------------------


def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "test-key")

    assert register(client).status_code == 401
    assert register(client, headers={"X-API-Key": "wrong"}).status_code == 401
    assert register(client, headers={"X-API-Key": "test-key-longer"}).status_code == 401
    assert register(client, headers={"X-API-Key": "test-key"}).status_code == 200

    # Non-/v1 endpoints stay open.
    assert client.get("/health").status_code == 200


def test_api_key_not_required_when_unset(client):
    assert register(client).status_code == 200


# --- health / ready / lifespan -------------------------------------------------


def test_health(client):
    assert client.get("/health").json() == {"ok": True}


def test_ready_with_fresh_heartbeat(client, fake_db):
    run(fake_db.worker_heartbeat.insert_one({"_id": "scheduler", "last_tick_at": datetime.now(UTC)}))
    r = client.get("/ready")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_ready_with_stale_heartbeat(client, fake_db):
    stale = datetime.now(UTC) - timedelta(seconds=3 * settings.scheduler_interval_seconds + 5)
    run(fake_db.worker_heartbeat.insert_one({"_id": "scheduler", "last_tick_at": stale}))
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["reason"] == "worker heartbeat stale"


def test_ready_without_heartbeat(client):
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["reason"] == "no worker heartbeat"


def test_ready_when_mongo_unreachable(client, fake_db, monkeypatch):
    async def failing_command(*args, **kwargs):
        raise RuntimeError("no mongo")

    monkeypatch.setattr(fake_db, "command", failing_command)
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["reason"] == "mongo unavailable"


def test_lifespan_creates_indexes_and_closes_apns(fake_db, monkeypatch):
    closed = []

    async def fake_close():
        closed.append(True)

    monkeypatch.setattr(main, "close_client", fake_close)
    with TestClient(main.app) as c:
        assert c.get("/health").status_code == 200

    push_log_idx = run(fake_db.push_log.index_information())
    events_idx = run(fake_db.events_daily.index_information())
    installs_idx = run(fake_db.installs.index_information())

    ttl = {name: spec.get("expireAfterSeconds") for name, spec in push_log_idx.items()}
    assert ttl["sent_at_1"] == 35 * 24 * 60 * 60
    ttl = {name: spec.get("expireAfterSeconds") for name, spec in events_idx.items()}
    assert ttl["updated_at_1"] == 35 * 24 * 60 * 60
    assert any(spec["key"][0][0] == "push_enabled" for spec in installs_idx.values())
    assert closed == [True]


@pytest.mark.parametrize("path", ["/v1/devices/register", "/v1/events"])
def test_post_routes_exist(client, path):
    # Empty bodies are validation errors, not 404/405.
    assert client.post(path, json={}).status_code == 422


def test_register_always_reports_that_install_has_secret(client):
    first = register(client)
    assert first.json()["install_has_secret"] is True
    assert "install_secret" in first.json()
    # A later call without the header (an older build that discarded the secret)
    # gets no new secret, but learns that one exists so it can start over.
    again = register(client)
    assert again.json() == {"ok": True, "install_has_secret": True}
