from datetime import datetime, timedelta
from typing import Optional

def should_send_daily_checkin(
    local_dt: datetime,
    daily_enabled: bool,
    daily_time: str,
    window_seconds: int,
) -> bool:
    if not daily_enabled:
        return False
    hh, mm = daily_time.split(":")
    target = local_dt.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
    if local_dt < target:
        return False
    delta_seconds = (local_dt - target).total_seconds()
    return 0 <= delta_seconds < window_seconds

def should_send_focus_first_step_nudge(now_utc: datetime, focus_started_at: Optional[datetime], focus_first_step_set: bool) -> bool:
    if not focus_started_at:
        return False
    if focus_first_step_set:
        return False
    # send if started between 7 and 10 minutes ago (a “window” prevents repeated sends)
    delta = now_utc - focus_started_at
    return timedelta(minutes=7) <= delta <= timedelta(minutes=10)

def should_send_capture_sort_nudge(captures_count: int, threshold: int = 8) -> bool:
    return captures_count >= threshold
