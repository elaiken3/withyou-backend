from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, Literal


class DeviceRegisterIn(BaseModel):
    install_id: str
    device_token: str
    timezone: str = "America/New_York"
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
    quiet_hours: QuietHours = QuietHours(start="22:00", end="08:00")
    max_push_per_day: int = 2
    daily_checkin: DailyCheckin = DailyCheckin()
    focus_nudges: Dict[str, bool] = {"enabled": True}
    capture_nudges: Dict[str, bool] = {"enabled": True}
    refocus_nudges: Dict[str, bool] = {"enabled": False}


class EventIn(BaseModel):
    install_id: str
    event_type: str
    ts: str  # ISO timestamp (UTC recommended)
    meta: Optional[Dict[str, Any]] = None
