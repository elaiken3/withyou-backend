"""Centralized default values for prefs and scheduling behavior."""

from datetime import timedelta

DEFAULT_TIMEZONE = "America/New_York"

DEFAULT_QUIET_HOURS = {"start": "22:00", "end": "08:00"}

DEFAULT_MAX_PUSH_PER_DAY = 2
MAX_PUSH_PER_DAY_LIMIT = 5

DEFAULT_DAILY_CHECKIN = {"enabled": False, "time": "09:00"}

# The daily check-in is sent once at or after the chosen local time. If the
# worker misses that exact minute (deploy, restart, slow tick, quiet hours
# ending), it may still go out within this window. After that the day is
# simply skipped: no catch-up sends.
DAILY_CHECKIN_GRACE = timedelta(hours=2)

# Focus nudges are opt-in. The focus first-step nudge fires 7-10 minutes into a
# focus session, which interrupts the very session it is meant to support
# ("During a Focus Session: nothing else matters"). It is only sent when the
# user explicitly turns it on in the app.
DEFAULT_FOCUS_NUDGES = {"enabled": False}
DEFAULT_CAPTURE_NUDGES = {"enabled": True}
DEFAULT_REFOCUS_NUDGES = {"enabled": False}

CAPTURE_SORT_THRESHOLD = 8
