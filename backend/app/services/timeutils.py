from datetime import datetime, time
from zoneinfo import ZoneInfo

def parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))

def in_quiet_hours(local_dt: datetime, start: str, end: str) -> bool:
    s = parse_hhmm(start)
    e = parse_hhmm(end)
    t = local_dt.time()

    # If quiet hours wrap midnight (common)
    if s <= e:
        return s <= t < e
    return (t >= s) or (t < e)

def local_now(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))
