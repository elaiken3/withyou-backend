from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from backend.app.services.rules import (
    should_send_capture_sort_nudge,
    should_send_daily_checkin,
    should_send_focus_first_step_nudge,
)

NY = ZoneInfo("America/New_York")


@pytest.mark.parametrize(
    "local_time, expected",
    [
        ((8, 59, 59), False),  # before the chosen time
        ((9, 0, 0), True),  # exactly on time
        ((9, 0, 30), True),
        ((9, 1, 1), True),  # a late tick no longer loses the day
        ((10, 59, 59), True),  # still inside the 2 h grace window
        ((11, 0, 0), False),  # grace window over
        ((15, 0, 0), False),
    ],
)
def test_daily_checkin_grace_window(local_time, expected):
    local_dt = datetime(2026, 2, 10, *local_time, tzinfo=NY)
    assert should_send_daily_checkin(local_dt, True, "09:00") is expected


def test_daily_checkin_disabled():
    local_dt = datetime(2026, 2, 10, 9, 0, tzinfo=NY)
    assert should_send_daily_checkin(local_dt, False, "09:00") is False


def test_daily_checkin_custom_grace():
    local_dt = datetime(2026, 2, 10, 9, 10, tzinfo=NY)
    assert should_send_daily_checkin(local_dt, True, "09:00", grace=timedelta(minutes=5)) is False
    assert should_send_daily_checkin(local_dt, True, "09:00", grace=timedelta(minutes=15)) is True


def test_daily_checkin_window_does_not_cross_local_midnight():
    # 23:30 target: at 00:30 the next local day has its own (future) target.
    assert should_send_daily_checkin(datetime(2026, 2, 10, 23, 45, tzinfo=NY), True, "23:30") is True
    assert should_send_daily_checkin(datetime(2026, 2, 11, 0, 30, tzinfo=NY), True, "23:30") is False


def test_focus_first_step_window():
    now = datetime.now(UTC)
    started = now - timedelta(minutes=8)
    assert should_send_focus_first_step_nudge(now, started, False) is True
    assert should_send_focus_first_step_nudge(now, started, True) is False
    assert should_send_focus_first_step_nudge(now, now - timedelta(minutes=5), False) is False
    assert should_send_focus_first_step_nudge(now, now - timedelta(minutes=11), False) is False
    assert should_send_focus_first_step_nudge(now, None, False) is False


def test_focus_first_step_accepts_naive_mongo_datetime():
    # Mongo returns naive datetimes (UTC); comparing must not raise.
    now = datetime(2026, 2, 10, 12, 0, tzinfo=UTC)
    started_naive = datetime(2026, 2, 10, 11, 52)
    assert should_send_focus_first_step_nudge(now, started_naive, False) is True


def test_capture_sort_threshold():
    assert should_send_capture_sort_nudge(7) is False
    assert should_send_capture_sort_nudge(8) is True
    assert should_send_capture_sort_nudge(3, threshold=3) is True
