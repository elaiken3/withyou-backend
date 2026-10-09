from datetime import datetime, timedelta

from .defaults import CAPTURE_SORT_THRESHOLD, DAILY_CHECKIN_GRACE
from .timeutils import as_utc, parse_hhmm


def should_send_daily_checkin(
    local_dt: datetime,
    daily_enabled: bool,
    daily_time: str,
    grace: timedelta = DAILY_CHECKIN_GRACE,
) -> bool:
    """True from the chosen local time until ``grace`` later (same local day).

    The caller guards this with a per-day dedupe key, so it is sent at most
    once per local day even though this stays true for many ticks.
    """
    if not daily_enabled:
        return False
    t = parse_hhmm(daily_time)
    target = local_dt.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
    if local_dt < target:
        return False
    return local_dt - target < grace


def should_send_focus_first_step_nudge(
    now_utc: datetime,
    focus_started_at: datetime | None,
    focus_first_step_set: bool,
) -> bool:
    if not focus_started_at:
        return False
    if focus_first_step_set:
        return False
    # send if started between 7 and 10 minutes ago (a "window" prevents repeated sends)
    delta = as_utc(now_utc) - as_utc(focus_started_at)
    return timedelta(minutes=7) <= delta <= timedelta(minutes=10)


def should_send_capture_sort_nudge(captures_count: int, threshold: int = CAPTURE_SORT_THRESHOLD) -> bool:
    return captures_count >= threshold
