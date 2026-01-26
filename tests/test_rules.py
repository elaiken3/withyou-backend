from datetime import datetime, timezone, timedelta
from backend.app.services.rules import should_send_focus_first_step_nudge

def test_focus_first_step_window():
    now = datetime.now(timezone.utc)
    started = now - timedelta(minutes=8)
    assert should_send_focus_first_step_nudge(now, started, False) is True
    assert should_send_focus_first_step_nudge(now, started, True) is False
