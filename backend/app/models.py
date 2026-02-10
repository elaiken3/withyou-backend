from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal

from .services.defaults import (
    DEFAULT_TIMEZONE,
    DEFAULT_QUIET_HOURS,
    DEFAULT_MAX_PUSH_PER_DAY,
    DEFAULT_DAILY_CHECKIN,
    DEFAULT_FOCUS_NUDGES,
    DEFAULT_CAPTURE_NUDGES,
    DEFAULT_REFOCUS_NUDGES,
)

class DeviceRegisterIn(BaseModel):
    install_id: str
    device_token: str
    timezone: str = DEFAULT_TIMEZONE
    push_enabled: bool = True

    # NEW — tells backend which APNs host to use
    # "sandbox" = Xcode / debug
    # "production" = TestFlight / App Store
    apns_environment: Optional[Literal["sandbox", "production"]] = None


class QuietHours(BaseModel):
    start: str  # "22:00"
    end: str    # "08:00"


class DailyCheckin(BaseModel):
    enabled: bool = False
    time: str = "09:00"  # local time


class PrefsIn(BaseModel):
    quiet_hours: QuietHours = QuietHours(**DEFAULT_QUIET_HOURS)
    max_push_per_day: int = DEFAULT_MAX_PUSH_PER_DAY
    daily_checkin: DailyCheckin = DailyCheckin(**DEFAULT_DAILY_CHECKIN)
    focus_nudges: Dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_FOCUS_NUDGES))
    capture_nudges: Dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_CAPTURE_NUDGES))
    refocus_nudges: Dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_REFOCUS_NUDGES))


class EventIn(BaseModel):
    install_id: str
    event_type: Literal[
        "capture_added",
        "refocus_opened",
        "focus_session_started",
        "focus_first_step_set",
    ]
    ts: str  # ISO timestamp (UTC recommended)
    meta: Optional[Dict[str, Any]] = None
