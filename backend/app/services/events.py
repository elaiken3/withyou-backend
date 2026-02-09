"""Builds event aggregation updates for daily rollups."""

from datetime import datetime, timezone
from typing import Dict, Any, Tuple, Optional


def build_daily_event_update(
    install_id: str,
    event_type: str,
    ts_utc: datetime,
    meta: Optional[Dict[str, Any]],
) -> Tuple[str, Dict[str, Any]]:
    day = ts_utc.date().isoformat()

    doc_id = f"{install_id}|{day}"
    update: Dict[str, Any] = {
        "$setOnInsert": {"install_id": install_id, "date": day},
        "$set": {"updated_at": datetime.now(timezone.utc)},
    }

    if event_type == "capture_added":
        inc = int((meta or {}).get("count", 1))
        update["$inc"] = {"captures_count": inc}
    elif event_type == "refocus_opened":
        update["$inc"] = {"refocus_opens_count": 1}
    elif event_type == "focus_session_started":
        update["$set"]["focus_started_at"] = ts_utc
        update["$set"]["focus_first_step_set"] = bool(
            (meta or {}).get("has_first_step", False)
        )
    elif event_type == "focus_first_step_set":
        update["$set"]["focus_first_step_set"] = True
        update["$set"]["focus_first_step_set_at"] = ts_utc

    return doc_id, update
