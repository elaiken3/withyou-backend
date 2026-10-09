from datetime import UTC, datetime
from typing import Annotated, Literal

from dateutil.parser import isoparse
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from .services.defaults import (
    DEFAULT_CAPTURE_NUDGES,
    DEFAULT_DAILY_CHECKIN,
    DEFAULT_FOCUS_NUDGES,
    DEFAULT_MAX_PUSH_PER_DAY,
    DEFAULT_QUIET_HOURS,
    DEFAULT_REFOCUS_NUDGES,
    DEFAULT_TIMEZONE,
    MAX_PUSH_PER_DAY_LIMIT,
)
from .services.timeutils import is_valid_timezone

INSTALL_ID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"
DEVICE_TOKEN_PATTERN = r"^[0-9A-Fa-f]{64,200}$"
HHMM_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"

InstallId = Annotated[str, Field(pattern=INSTALL_ID_PATTERN)]
HHMM = Annotated[str, Field(pattern=HHMM_PATTERN)]


def _check_timezone(value: str) -> str:
    if not is_valid_timezone(value):
        raise ValueError("timezone must be a valid IANA time zone name, e.g. America/New_York")
    return value


Timezone = Annotated[str, AfterValidator(_check_timezone)]


class DeviceRegisterIn(BaseModel):
    install_id: InstallId
    device_token: Annotated[str, Field(pattern=DEVICE_TOKEN_PATTERN)]
    timezone: Timezone = DEFAULT_TIMEZONE
    push_enabled: bool = True

    # Tells the backend which APNs host to use
    # "sandbox" = Xcode / debug
    # "production" = TestFlight / App Store
    apns_environment: Literal["sandbox", "production"] | None = None


class QuietHours(BaseModel):
    start: HHMM  # "22:00"
    end: HHMM  # "08:00"


class DailyCheckin(BaseModel):
    enabled: bool = False
    time: HHMM = "09:00"  # local time


class PrefsIn(BaseModel):
    quiet_hours: QuietHours = Field(default_factory=lambda: QuietHours(**DEFAULT_QUIET_HOURS))
    max_push_per_day: int = Field(DEFAULT_MAX_PUSH_PER_DAY, ge=0, le=MAX_PUSH_PER_DAY_LIMIT)
    daily_checkin: DailyCheckin = Field(default_factory=lambda: DailyCheckin(**DEFAULT_DAILY_CHECKIN))
    focus_nudges: dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_FOCUS_NUDGES))
    capture_nudges: dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_CAPTURE_NUDGES))
    refocus_nudges: dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_REFOCUS_NUDGES))


class EventMeta(BaseModel):
    # Only these keys are used; anything else is dropped, never stored.
    model_config = ConfigDict(extra="ignore")

    count: int | None = Field(None, ge=1, le=100)  # capture_added: number of captures
    has_first_step: bool | None = None  # focus_session_started


class EventIn(BaseModel):
    install_id: InstallId
    event_type: Literal[
        "capture_added",
        "refocus_opened",
        "focus_session_started",
        "focus_first_step_set",
    ]
    ts: datetime  # ISO 8601 string; a value without an offset is treated as UTC
    meta: EventMeta | None = None

    @field_validator("ts", mode="before")
    @classmethod
    def _parse_ts(cls, value: object) -> datetime:
        if not isinstance(value, str):
            raise ValueError("ts must be an ISO 8601 timestamp string")
        try:
            parsed = isoparse(value)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)
        except (ValueError, OverflowError) as e:
            raise ValueError("ts must be an ISO 8601 timestamp string") from e
