import asyncio
import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from backend.app.models import PrefsIn
from backend.app.services import scheduler, timeutils
from backend.app.services.apns import APNSTokenInvalid

INSTALL_ID = "install-0001"
TOKEN = "ab" * 32
NY = "America/New_York"

# 01:30 UTC on Feb 10 == 20:30 on Feb 9 in New York (UTC-5).
NOW_UTC = datetime(2026, 2, 10, 1, 30, tzinfo=UTC)
NY_DAY = "2026-02-09"
UTC_DAY = "2026-02-10"


def make_prefs(**overrides):
    p = PrefsIn(
        quiet_hours={"start": "23:00", "end": "07:00"},
        daily_checkin={"enabled": True, "time": "20:00"},
        capture_nudges={"enabled": False},
    ).model_dump()
    p.update(overrides)
    return p


async def seed(fake_db, install_id=INSTALL_ID, tz=NY, prefs=None, token=TOKEN, push_enabled=True):
    await fake_db.installs.insert_one({"_id": install_id, "timezone": tz, "push_enabled": push_enabled})
    if prefs is not None:
        await fake_db.prefs.insert_one({"_id": install_id, **prefs})
    if token:
        await fake_db.devices.insert_one(
            {"_id": token, "install_id": install_id, "updated_at": datetime(2026, 1, 1), "apns_environment": "sandbox"}
        )


@pytest.fixture
def sent(monkeypatch):
    """Replace APNs with a recorder."""
    calls = []

    async def fake_send_alert(token, title, body, badge=None, deep_link=None, apns_environment=None):
        calls.append({"token": token, "body": body, "deep_link": deep_link, "apns_environment": apns_environment})

    monkeypatch.setattr(scheduler, "send_alert", fake_send_alert)
    return calls


def set_send_error(monkeypatch, exc):
    async def failing_send_alert(*args, **kwargs):
        raise exc

    monkeypatch.setattr(scheduler, "send_alert", failing_send_alert)


async def test_daily_checkin_uses_install_local_day(fake_db, sent):
    await seed(fake_db, prefs=make_prefs())

    await scheduler.tick(now_utc=NOW_UTC)

    assert len(sent) == 1
    assert sent[0]["token"] == TOKEN
    assert sent[0]["deep_link"] == "withyou://today"
    assert sent[0]["apns_environment"] == "sandbox"
    doc = await fake_db.push_log.find_one({"_id": f"{INSTALL_ID}|{NY_DAY}|daily_checkin"})
    assert doc is not None
    assert doc["date"] == NY_DAY
    assert await fake_db.push_log.count_documents({"date": UTC_DAY}) == 0

    # Later ticks on the same local day do not send it again.
    await scheduler.tick(now_utc=NOW_UTC + timedelta(minutes=10))
    await scheduler.tick(now_utc=NOW_UTC + timedelta(minutes=60))
    assert len(sent) == 1


async def test_heartbeat_written(fake_db, sent):
    await scheduler.tick(now_utc=NOW_UTC)
    hb = await fake_db.worker_heartbeat.find_one({"_id": "scheduler"})
    assert hb["last_tick_at"] == NOW_UTC.replace(tzinfo=None)


@pytest.mark.parametrize(
    "minutes_after_target, expected_sends",
    [(-1, 0), (0, 1), (90, 1), (119, 1), (120, 0), (180, 0)],
)
async def test_daily_checkin_grace_window(fake_db, sent, minutes_after_target, expected_sends):
    # Target 20:00 local == 01:00 UTC; no quiet hours in the way.
    await seed(fake_db, prefs=make_prefs(quiet_hours={"start": "03:00", "end": "04:00"}))
    now = datetime(2026, 2, 10, 1, 0, tzinfo=UTC) + timedelta(minutes=minutes_after_target)
    await scheduler.tick(now_utc=now)
    assert len(sent) == expected_sends


async def test_quiet_hours_block_sends(fake_db, sent):
    # 20:30 local is inside 20:00-08:00 quiet hours.
    await seed(fake_db, prefs=make_prefs(quiet_hours={"start": "20:00", "end": "08:00"}))
    await scheduler.tick(now_utc=NOW_UTC)
    assert sent == []
    assert await fake_db.push_log.count_documents({}) == 0


async def test_checkin_sent_when_quiet_hours_end_within_grace(fake_db, sent):
    # Check-in at 07:30, quiet hours end 08:00: it goes out at 08:00 instead of being lost.
    await seed(
        fake_db,
        prefs=make_prefs(
            quiet_hours={"start": "22:00", "end": "08:00"}, daily_checkin={"enabled": True, "time": "07:30"}
        ),
    )
    await scheduler.tick(now_utc=datetime(2026, 2, 10, 12, 45, tzinfo=UTC))  # 07:45 local
    assert sent == []
    await scheduler.tick(now_utc=datetime(2026, 2, 10, 13, 0, tzinfo=UTC))  # 08:00 local
    assert len(sent) == 1


async def test_daily_cap_counts_install_local_day(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(max_push_per_day=1))
    # Something already went out on the local day: cap reached.
    await fake_db.push_log.insert_one(
        {"_id": f"{INSTALL_ID}|{NY_DAY}|capture_sort", "install_id": INSTALL_ID, "date": NY_DAY, "type": "capture_sort"}
    )
    await scheduler.tick(now_utc=NOW_UTC)
    assert sent == []


async def test_daily_cap_ignores_other_days(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(max_push_per_day=1))
    # A push recorded under the UTC date is a different local day.
    await fake_db.push_log.insert_one(
        {"_id": f"{INSTALL_ID}|{UTC_DAY}|capture_sort", "install_id": INSTALL_ID, "date": UTC_DAY}
    )
    await scheduler.tick(now_utc=NOW_UTC)
    assert len(sent) == 1


async def test_zero_max_push_sends_nothing(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(max_push_per_day=0))
    await scheduler.tick(now_utc=NOW_UTC)
    assert sent == []


async def test_existing_claim_prevents_send(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(max_push_per_day=5))
    await fake_db.push_log.insert_one(
        {"_id": f"{INSTALL_ID}|{NY_DAY}|daily_checkin", "install_id": INSTALL_ID, "date": NY_DAY}
    )
    await scheduler.tick(now_utc=NOW_UTC)
    assert sent == []


async def test_concurrent_ticks_send_once(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(max_push_per_day=5))
    await asyncio.gather(scheduler.tick(now_utc=NOW_UTC), scheduler.tick(now_utc=NOW_UTC))
    assert len(sent) == 1


async def test_cap_rechecked_after_claim(fake_db, sent):
    # Another worker claimed two pushes after this worker's cap snapshot (0 sent).
    await seed(fake_db, prefs=make_prefs(max_push_per_day=2))
    for ntype in ("capture_sort", "focus_first_step"):
        await fake_db.push_log.insert_one(
            {"_id": f"{INSTALL_ID}|{NY_DAY}|{ntype}", "install_id": INSTALL_ID, "date": NY_DAY, "type": ntype}
        )
    local_dt = NOW_UTC.astimezone(timeutils.zone_or_utc(NY))
    a = scheduler._InstallNow(INSTALL_ID, make_prefs(max_push_per_day=2), local_dt, NY_DAY)
    device = await fake_db.devices.find_one({"_id": TOKEN})

    await scheduler._process_install(a, device=device, agg={}, sent_today=0, now_utc=NOW_UTC)

    assert sent == []
    assert await fake_db.push_log.find_one({"_id": f"{INSTALL_ID}|{NY_DAY}|daily_checkin"}) is None


async def test_failed_send_releases_claim_for_silent_retry(fake_db, sent, monkeypatch):
    await seed(fake_db, prefs=make_prefs())
    real_send = scheduler.send_alert
    set_send_error(monkeypatch, RuntimeError("APNs send failed: 500"))

    await scheduler.tick(now_utc=NOW_UTC)
    assert await fake_db.push_log.count_documents({}) == 0

    monkeypatch.setattr(scheduler, "send_alert", real_send)
    await scheduler.tick(now_utc=NOW_UTC + timedelta(minutes=1))
    assert len(sent) == 1
    assert await fake_db.push_log.count_documents({}) == 1


async def test_read_timeout_keeps_claim(fake_db, sent, monkeypatch):
    # The push may have been delivered; never risk a duplicate.
    await seed(fake_db, prefs=make_prefs())
    real_send = scheduler.send_alert
    set_send_error(monkeypatch, httpx.ReadTimeout("timed out"))

    await scheduler.tick(now_utc=NOW_UTC)
    assert await fake_db.push_log.count_documents({}) == 1

    monkeypatch.setattr(scheduler, "send_alert", real_send)
    await scheduler.tick(now_utc=NOW_UTC + timedelta(minutes=1))
    assert sent == []


async def test_invalid_token_removed(fake_db, sent, monkeypatch):
    await seed(fake_db, prefs=make_prefs())
    set_send_error(monkeypatch, APNSTokenInvalid(410, "Unregistered"))

    await scheduler.tick(now_utc=NOW_UTC)

    assert await fake_db.devices.find_one({"_id": TOKEN}) is None
    assert await fake_db.push_log.count_documents({}) == 0


async def test_uses_most_recently_updated_device(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(), token=None)
    await fake_db.devices.insert_many(
        [
            {"_id": "01" * 32, "install_id": INSTALL_ID, "updated_at": datetime(2026, 1, 1)},
            {"_id": "02" * 32, "install_id": INSTALL_ID, "updated_at": datetime(2026, 2, 1)},
            {"_id": "03" * 32, "install_id": INSTALL_ID, "updated_at": datetime(2025, 12, 1)},
            {"_id": "04" * 32, "install_id": INSTALL_ID},
        ]
    )
    await scheduler.tick(now_utc=NOW_UTC)
    assert [c["token"] for c in sent] == ["02" * 32]


async def test_bad_stored_timezone_falls_back_to_utc(fake_db, sent, monkeypatch, caplog):
    monkeypatch.setattr(timeutils, "_warned_bad_timezones", set())
    prefs = make_prefs(quiet_hours={"start": "12:00", "end": "13:00"}, daily_checkin={"enabled": True, "time": "01:00"})
    await seed(fake_db, tz="Mars/Olympus_Mons", prefs=prefs)

    with caplog.at_level(logging.WARNING):
        await scheduler.tick(now_utc=NOW_UTC)  # 01:30 UTC
        await scheduler.tick(now_utc=NOW_UTC + timedelta(minutes=1))

    assert len(sent) == 1
    assert await fake_db.push_log.find_one({"_id": f"{INSTALL_ID}|{UTC_DAY}|daily_checkin"}) is not None
    assert len([r for r in caplog.records if "Mars/Olympus_Mons" in r.getMessage()]) == 1


async def test_one_bad_install_does_not_block_others(fake_db, sent):
    await seed(fake_db, install_id="install-bad1", token="ee" * 32, prefs=make_prefs(quiet_hours={"start": "x"}))
    await seed(fake_db, prefs=make_prefs())
    await scheduler.tick(now_utc=NOW_UTC)
    assert [c["token"] for c in sent] == [TOKEN]


async def test_no_prefs_sends_nothing(fake_db, sent):
    await seed(fake_db, prefs=None)
    await scheduler.tick(now_utc=NOW_UTC)
    assert sent == []


async def test_push_disabled_install_skipped(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(), push_enabled=False)
    await scheduler.tick(now_utc=NOW_UTC)
    assert sent == []


async def test_no_device_sends_nothing(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(), token=None)
    await scheduler.tick(now_utc=NOW_UTC)
    assert sent == []
    assert await fake_db.push_log.count_documents({}) == 0


async def test_capture_sort_uses_local_day_rollup_and_one_push_per_tick(fake_db, sent):
    await seed(fake_db, prefs=make_prefs(capture_nudges={"enabled": True}))
    await fake_db.events_daily.insert_one(
        {"_id": f"{INSTALL_ID}|{NY_DAY}", "install_id": INSTALL_ID, "date": NY_DAY, "captures_count": 8}
    )

    await scheduler.tick(now_utc=NOW_UTC)
    assert [c["deep_link"] for c in sent] == ["withyou://today"]  # check-in first, one push per tick

    await scheduler.tick(now_utc=NOW_UTC + timedelta(minutes=1))
    assert [c["deep_link"] for c in sent] == ["withyou://today", "withyou://inbox"]

    # Cap of 2 reached.
    await scheduler.tick(now_utc=NOW_UTC + timedelta(minutes=2))
    assert len(sent) == 2


async def test_focus_nudge_is_opt_in(fake_db, sent):
    prefs = make_prefs(daily_checkin={"enabled": False, "time": "09:00"})
    assert prefs["focus_nudges"] == {"enabled": False}
    await seed(fake_db, prefs=prefs)
    started = (NOW_UTC - timedelta(minutes=8)).replace(tzinfo=None)  # stored naive, as Mongo returns it
    await fake_db.events_daily.insert_one(
        {"_id": f"{INSTALL_ID}|{NY_DAY}", "install_id": INSTALL_ID, "focus_started_at": started}
    )

    await scheduler.tick(now_utc=NOW_UTC)
    assert sent == []

    await fake_db.prefs.update_one({"_id": INSTALL_ID}, {"$set": {"focus_nudges": {"enabled": True}}})
    await scheduler.tick(now_utc=NOW_UTC)
    assert [c["deep_link"] for c in sent] == ["withyou://focus"]


async def test_pages_through_all_installs(fake_db, sent, monkeypatch):
    monkeypatch.setattr(scheduler, "INSTALL_PAGE_SIZE", 2)
    for i in range(5):
        await seed(fake_db, install_id=f"install-000{i}", token=f"{i:02d}" * 32, prefs=make_prefs())
    await scheduler.tick(now_utc=NOW_UTC)
    assert sorted(c["token"] for c in sent) == sorted(f"{i:02d}" * 32 for i in range(5))
