from datetime import datetime, timedelta
from typing import Optional

def should_send_daily_checkin(local_dt, daily_enabled: bool, daily_time: str) -> bool:
    if not daily_enabled:
        return False
    hh, mm = daily_time.split(":")
    return local_dt.hour == int(hh) and local_dt.minute == int(mm)

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
