import logging
from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger("withyou.timeutils")

_warned_bad_timezones: set[str] = set()


def parse_hhmm(s: str) -> time:
    hh, mm = s.split(":")
    return time(int(hh), int(mm))


def in_quiet_hours(local_dt: datetime, start: str, end: str) -> bool:
    s = parse_hhmm(start)
    e = parse_hhmm(end)
    t = local_dt.time()

    if s <= e:
        return s <= t < e
    # Quiet hours wrap midnight (the common case, e.g. 22:00-08:00)
    return (t >= s) or (t < e)


def is_valid_timezone(tz_name: str) -> bool:
    try:
        ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError, OSError):
        return False
    return True


def zone_or_utc(tz_name: str | None) -> ZoneInfo:
    """Return the zone for a stored timezone name, or UTC if it is unusable.

    Stored data can predate validation; a bad value must not break the
    scheduler for that install on every tick. Each bad name is logged once
    per process.
    """
    if tz_name and is_valid_timezone(tz_name):
        return ZoneInfo(tz_name)

    key = str(tz_name)
    if key not in _warned_bad_timezones:
        _warned_bad_timezones.add(key)
        logger.warning("invalid stored timezone %r; using UTC", tz_name)
    return ZoneInfo("UTC")


def local_day(dt: datetime, tz: ZoneInfo) -> str:
    """The install's local calendar date (YYYY-MM-DD) for an aware datetime."""
    return dt.astimezone(tz).date().isoformat()


def as_utc(dt: datetime) -> datetime:
    """Mongo returns naive datetimes (stored as UTC); make them aware."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def local_now(tz_name: str) -> datetime:
    return datetime.now(ZoneInfo(tz_name))
