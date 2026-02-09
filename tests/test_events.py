from datetime import datetime, timezone

from backend.app.services.events import build_daily_event_update


def test_build_daily_event_update_capture_added():
    ts_utc = datetime(2026, 2, 9, 12, 0, tzinfo=timezone.utc)
    doc_id, update = build_daily_event_update(
        install_id="install-1",
        event_type="capture_added",
        ts_utc=ts_utc,
        meta={"count": 3},
    )

    assert doc_id == "install-1|2026-02-09"
    assert update["$setOnInsert"]["install_id"] == "install-1"
    assert update["$setOnInsert"]["date"] == "2026-02-09"
    assert update["$inc"]["captures_count"] == 3


def test_build_daily_event_update_focus_session_started():
    ts_utc = datetime(2026, 2, 9, 12, 30, tzinfo=timezone.utc)
    doc_id, update = build_daily_event_update(
        install_id="install-2",
        event_type="focus_session_started",
        ts_utc=ts_utc,
        meta={"has_first_step": True},
    )

    assert doc_id == "install-2|2026-02-09"
    assert update["$set"]["focus_started_at"] == ts_utc
    assert update["$set"]["focus_first_step_set"] is True
