import logging
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

import pytest

from backend.app.services import timeutils
from backend.app.services.timeutils import (
    as_utc,
    in_quiet_hours,
    is_valid_timezone,
    local_day,
    parse_hhmm,
    zone_or_utc,
)

NY = ZoneInfo("America/New_York")


def test_parse_hhmm():
    assert parse_hhmm("00:00") == time(0, 0)
    assert parse_hhmm("23:59") == time(23, 59)


@pytest.mark.parametrize(
    "hh, mm, expected",
    [
        (21, 59, False),
        (22, 0, True),  # start is inclusive
        (23, 30, True),
        (0, 0, True),  # wraps past midnight
        (3, 0, True),
        (7, 59, True),
        (8, 0, False),  # end is exclusive
        (12, 0, False),
    ],
)
def test_quiet_hours_wrapping_midnight(hh, mm, expected):
    local_dt = datetime(2026, 2, 10, hh, mm, tzinfo=NY)
    assert in_quiet_hours(local_dt, "22:00", "08:00") is expected


@pytest.mark.parametrize(
    "hh, mm, expected",
    [(12, 59, False), (13, 0, True), (13, 59, True), (14, 0, False)],
)
def test_quiet_hours_same_day(hh, mm, expected):
    local_dt = datetime(2026, 2, 10, hh, mm, tzinfo=NY)
    assert in_quiet_hours(local_dt, "13:00", "14:00") is expected


def test_quiet_hours_equal_start_end_means_never_quiet():
    assert in_quiet_hours(datetime(2026, 2, 10, 9, 0, tzinfo=NY), "09:00", "09:00") is False


def test_is_valid_timezone():
    assert is_valid_timezone("America/New_York") is True
    assert is_valid_timezone("UTC") is True
    for bad in ["Mars/Base", "", "America", "../etc/passwd", "x" * 300]:
        assert is_valid_timezone(bad) is False, bad


def test_zone_or_utc_falls_back_and_logs_once(monkeypatch, caplog):
    monkeypatch.setattr(timeutils, "_warned_bad_timezones", set())
    with caplog.at_level(logging.WARNING, logger="withyou.timeutils"):
        assert zone_or_utc("Mars/Base") == ZoneInfo("UTC")
        assert zone_or_utc("Mars/Base") == ZoneInfo("UTC")
    assert len([r for r in caplog.records if "Mars/Base" in r.getMessage()]) == 1
    assert zone_or_utc("America/New_York") == NY


def test_local_day_uses_install_timezone():
    # 01:30 UTC on Feb 10 is still Feb 9 (20:30) in New York.
    now_utc = datetime(2026, 2, 10, 1, 30, tzinfo=UTC)
    assert local_day(now_utc, NY) == "2026-02-09"
    assert local_day(now_utc, ZoneInfo("UTC")) == "2026-02-10"
    assert local_day(now_utc, ZoneInfo("Asia/Tokyo")) == "2026-02-10"


def test_as_utc():
    naive = datetime(2026, 2, 10, 12, 0)
    assert as_utc(naive) == datetime(2026, 2, 10, 12, 0, tzinfo=UTC)
    aware = datetime(2026, 2, 10, 7, 0, tzinfo=NY)
    assert as_utc(aware) == datetime(2026, 2, 10, 12, 0, tzinfo=UTC)
