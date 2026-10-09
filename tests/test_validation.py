import pytest
from pydantic import ValidationError

from backend.app.models import DeviceRegisterIn, EventIn, PrefsIn

GOOD_TOKEN = "ab" * 32  # 64 hex chars
INSTALL_ID = "install-0001"


def register_body(**overrides):
    body = {
        "install_id": INSTALL_ID,
        "device_token": GOOD_TOKEN,
        "timezone": "America/New_York",
        "push_enabled": True,
    }
    body.update(overrides)
    return body


def event_body(**overrides):
    body = {"install_id": INSTALL_ID, "event_type": "capture_added", "ts": "2026-02-10T12:00:00Z"}
    body.update(overrides)
    return body


# --- model level: valid boundaries -----------------------------------------


def test_register_accepts_valid_boundaries():
    DeviceRegisterIn(**register_body(install_id="a" * 8, device_token="A" * 64))
    DeviceRegisterIn(**register_body(install_id="E621E1F8-C36C-495A-93FC-0C247A3E6E5F", device_token="f" * 200))
    DeviceRegisterIn(**register_body(install_id="b" * 64, timezone="UTC"))


def test_prefs_accepts_valid_boundaries():
    PrefsIn(max_push_per_day=0)
    PrefsIn(max_push_per_day=5)
    PrefsIn(quiet_hours={"start": "00:00", "end": "23:59"}, daily_checkin={"enabled": True, "time": "23:59"})


def test_prefs_defaults_keep_focus_nudges_opt_in():
    p = PrefsIn()
    assert p.focus_nudges == {"enabled": False}
    assert p.daily_checkin.enabled is False


def test_event_ts_parsing():
    e = EventIn(**event_body(ts="2026-02-10T07:00:00-05:00"))
    assert e.ts.isoformat() == "2026-02-10T12:00:00+00:00"
    naive = EventIn(**event_body(ts="2026-02-10T12:00:00"))
    assert naive.ts.isoformat() == "2026-02-10T12:00:00+00:00"


def test_event_meta_count_bounds_and_extra_keys():
    assert EventIn(**event_body(meta={"count": 1})).meta.count == 1
    assert EventIn(**event_body(meta={"count": 100})).meta.count == 100
    e = EventIn(**event_body(meta={"count": 2, "task_text": "never stored"}))
    assert e.meta.model_dump(exclude_none=True) == {"count": 2}


@pytest.mark.parametrize("count", [0, -1, 101, "abc", 2.5])
def test_event_meta_count_rejected(count):
    with pytest.raises(ValidationError):
        EventIn(**event_body(meta={"count": count}))


# --- route level: 422s -------------------------------------------------------


@pytest.mark.parametrize(
    "overrides",
    [
        {"install_id": "short"},  # < 8 chars
        {"install_id": "x" * 65},  # > 64 chars
        {"install_id": "has spaces 123"},
        {"install_id": "under_score_1"},
        {"device_token": "xyz"},
        {"device_token": "g" * 64},  # not hex
        {"device_token": "a" * 63},
        {"device_token": "a" * 201},
        {"timezone": "Mars/Base"},
        {"timezone": ""},
        {"timezone": "America"},
        {"apns_environment": "staging"},
    ],
)
def test_register_validation_errors(client, overrides):
    r = client.post("/v1/devices/register", json=register_body(**overrides))
    assert r.status_code == 422, r.text


@pytest.mark.parametrize(
    "body",
    [
        {"quiet_hours": {"start": "24:00", "end": "08:00"}},
        {"quiet_hours": {"start": "9:00", "end": "08:00"}},
        {"quiet_hours": {"start": "22:00", "end": "08:60"}},
        {"quiet_hours": {"start": "22:00"}},
        {"max_push_per_day": 6},
        {"max_push_per_day": -1},
        {"daily_checkin": {"enabled": True, "time": "25:00"}},
        {"daily_checkin": {"enabled": True, "time": "noon"}},
    ],
)
def test_prefs_validation_errors(client, body):
    r = client.put(f"/v1/prefs/{INSTALL_ID}", json=body, headers={"X-Install-Secret": "s"})
    assert r.status_code == 422, r.text


def test_prefs_path_install_id_validated(client):
    r = client.put("/v1/prefs/short", json={}, headers={"X-Install-Secret": "s"})
    assert r.status_code == 422


def test_delete_path_install_id_validated(client):
    r = client.delete("/v1/installs/bad_id_with_underscores", headers={"X-Install-Secret": "s"})
    assert r.status_code == 422


@pytest.mark.parametrize(
    "overrides",
    [
        {"meta": {"count": 0}},
        {"meta": {"count": -3}},
        {"meta": {"count": 101}},
        {"meta": {"count": "abc"}},
        {"ts": "yesterday"},
        {"ts": "2026-13-45T00:00:00Z"},
        {"ts": 1770724800},
        {"event_type": "task_completed"},
        {"install_id": "short"},
    ],
)
def test_event_validation_errors(client, overrides):
    r = client.post("/v1/events", json=event_body(**overrides), headers={"X-Install-Secret": "s"})
    assert r.status_code == 422, r.text
