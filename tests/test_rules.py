from datetime import datetime, timezone, timedelta
from backend.app.services.rules import should_send_focus_first_step_nudge, should_send_daily_checkin

def test_focus_first_step_window():
    now = datetime.now(timezone.utc)
    started = now - timedelta(minutes=8)
    assert should_send_focus_first_step_nudge(now, started, False) is True
    assert should_send_focus_first_step_nudge(now, started, True) is False


def test_daily_checkin_window():
    local_dt = datetime(2026, 2, 10, 9, 0, 30, tzinfo=timezone.utc)
    assert should_send_daily_checkin(local_dt, True, "09:00", window_seconds=60) is True
    late = datetime(2026, 2, 10, 9, 1, 1, tzinfo=timezone.utc)
    assert should_send_daily_checkin(late, True, "09:00", window_seconds=60) is False
