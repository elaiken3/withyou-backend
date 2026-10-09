from datetime import UTC, datetime

from backend.app.services.events import build_daily_event_update


def test_build_daily_event_update_capture_added():
    ts_utc = datetime(2026, 2, 9, 12, 0, tzinfo=UTC)
    doc_id, update = build_daily_event_update(
        install_id="install-1",
        event_type="capture_added",
        ts_utc=ts_utc,
        day="2026-02-09",
        meta={"count": 3},
    )

    assert doc_id == "install-1|2026-02-09"
    assert update["$setOnInsert"]["install_id"] == "install-1"
    assert update["$setOnInsert"]["date"] == "2026-02-09"
    assert update["$inc"]["captures_count"] == 3


def test_build_daily_event_update_capture_added_defaults_to_one():
    ts_utc = datetime(2026, 2, 9, 12, 0, tzinfo=UTC)
    _, update = build_daily_event_update("install-1", "capture_added", ts_utc, "2026-02-09", None)
    assert update["$inc"]["captures_count"] == 1


def test_build_daily_event_update_uses_given_local_day():
    # 02:00 UTC Feb 10 is Feb 9 in New York; the caller passes the local day.
    ts_utc = datetime(2026, 2, 10, 2, 0, tzinfo=UTC)
    doc_id, update = build_daily_event_update("install-1", "refocus_opened", ts_utc, "2026-02-09", None)
    assert doc_id == "install-1|2026-02-09"
    assert update["$inc"] == {"refocus_opens_count": 1}


def test_build_daily_event_update_focus_session_started():
    ts_utc = datetime(2026, 2, 9, 12, 30, tzinfo=UTC)
    doc_id, update = build_daily_event_update(
        install_id="install-2",
        event_type="focus_session_started",
        ts_utc=ts_utc,
        day="2026-02-09",
        meta={"has_first_step": True},
    )

    assert doc_id == "install-2|2026-02-09"
    assert update["$set"]["focus_started_at"] == ts_utc
    assert update["$set"]["focus_first_step_set"] is True
