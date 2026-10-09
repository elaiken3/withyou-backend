"""Builds event aggregation updates for daily rollups."""

from datetime import UTC, datetime
from typing import Any


def build_daily_event_update(
    install_id: str,
    event_type: str,
    ts_utc: datetime,
    day: str,
    meta: dict[str, Any] | None,
) -> tuple[str, dict[str, Any]]:
    """Return the (doc_id, update) for the install's rollup of ``day``.

    ``day`` is the install's local calendar date for the event (YYYY-MM-DD),
    so rollups line up with the scheduler's notion of "today".
    """
    meta = meta or {}
    doc_id = f"{install_id}|{day}"
    update: dict[str, Any] = {
        "$setOnInsert": {"install_id": install_id, "date": day},
        "$set": {"updated_at": datetime.now(UTC)},
    }

    if event_type == "capture_added":
        update["$inc"] = {"captures_count": meta.get("count") or 1}
    elif event_type == "refocus_opened":
        update["$inc"] = {"refocus_opens_count": 1}
    elif event_type == "focus_session_started":
        update["$set"]["focus_started_at"] = ts_utc
        update["$set"]["focus_first_step_set"] = bool(meta.get("has_first_step", False))
    elif event_type == "focus_first_step_set":
        update["$set"]["focus_first_step_set"] = True
        update["$set"]["focus_first_step_set_at"] = ts_utc

    return doc_id, update
