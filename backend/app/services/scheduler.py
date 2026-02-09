from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..db import installs, devices, prefs, events_daily
from .timeutils import in_quiet_hours
from .dedupe import can_send_today, already_sent, mark_sent
from .apns import send_alert
from .notifications import NOTIFICATION_TEMPLATES, dedupe_key
from .defaults import (
    DEFAULT_QUIET_HOURS,
    DEFAULT_MAX_PUSH_PER_DAY,
    DEFAULT_DAILY_CHECKIN,
)
from .rules import (
    should_send_daily_checkin,
    should_send_focus_first_step_nudge,
    should_send_capture_sort_nudge
)

async def tick():
    now_utc = datetime.now(timezone.utc)
    today_utc = now_utc.date().isoformat()

    print(f"[scheduler] tick ran at {now_utc.isoformat()}")

    try:
        cursor = installs.find({"push_enabled": True})
        async for inst in cursor:
            install_id = inst.get("_id")
            tz = inst.get("timezone", "America/New_York")

            try:
                # Load prefs (or defaults)
                p = await prefs.find_one({"_id": install_id}) or {}
                qh = p.get("quiet_hours") or DEFAULT_QUIET_HOURS
                max_per_day = int(p.get("max_push_per_day", DEFAULT_MAX_PUSH_PER_DAY))

                # Quiet hours check (local time)
                local_dt = datetime.now(ZoneInfo(tz))
                if in_quiet_hours(local_dt, qh["start"], qh["end"]):
                    # Uncomment if you want noisy logs:
                    # print(f"[scheduler] {install_id}: skipped (quiet hours)")
                    continue

                # Daily cap check
                if not await can_send_today(install_id, today_utc, max_per_day):
                    # print(f"[scheduler] {install_id}: skipped (daily cap reached)")
                    continue

                # Find device token
                dev = await devices.find_one({"install_id": install_id})
                if not dev:
                    # print(f"[scheduler] {install_id}: skipped (no device)")
                    continue
                token = dev["_id"]

                # Today's aggregate doc
                agg_id = f"{install_id}|{today_utc}"
                agg = await events_daily.find_one({"_id": agg_id}) or {}

                # Helper to send safely + mark sent
                async def _send_once(ntype: str, key: str, title: str, body: str, deep_link: str):
                    if await already_sent(key):
                        return False

                    try:
                        send_alert(token, title, body, deep_link=deep_link)
                    except Exception as e:
                        # Don't crash the worker on APNs failures
                        print(f"[scheduler] {install_id}: APNs error for {ntype}: {repr(e)}")
                        return False

                    await mark_sent(key, install_id, today_utc, ntype)
                    print(f"[scheduler] {install_id}: sent {ntype}")
                    return True

                # 1) Daily check-in
                dc = p.get("daily_checkin") or DEFAULT_DAILY_CHECKIN
                if should_send_daily_checkin(local_dt, bool(dc.get("enabled")), dc.get("time", "09:00")):
                    key = dedupe_key(install_id, today_utc, "daily_checkin")
                    tmpl = NOTIFICATION_TEMPLATES["daily_checkin"]
                    sent = await _send_once(
                        ntype="daily_checkin",
                        key=key,
                        title=tmpl["title"],
                        body=tmpl["body"],
                        deep_link=tmpl["deep_link"],
                    )
                    if sent:
                        continue  # one push per tick max

                # 2) Focus first-step nudge
                if (p.get("focus_nudges") or {}).get("enabled", False):
                    focus_started_at = agg.get("focus_started_at")
                    first_step_set = bool(agg.get("focus_first_step_set", False))

                    if focus_started_at and should_send_focus_first_step_nudge(now_utc, focus_started_at, first_step_set):
                        key = dedupe_key(install_id, today_utc, "focus_first_step")
                        tmpl = NOTIFICATION_TEMPLATES["focus_first_step"]
                        sent = await _send_once(
                            ntype="focus_first_step",
                            key=key,
                            title=tmpl["title"],
                            body=tmpl["body"],
                            deep_link=tmpl["deep_link"],
                        )
                        if sent:
                            continue

                # 3) Capture sort nudge
                if (p.get("capture_nudges") or {}).get("enabled", False):
                    captures = int(agg.get("captures_count", 0))
                    if should_send_capture_sort_nudge(captures, threshold=8):
                        key = dedupe_key(install_id, today_utc, "capture_sort")
                        tmpl = NOTIFICATION_TEMPLATES["capture_sort"]
                        sent = await _send_once(
                            ntype="capture_sort",
                            key=key,
                            title=tmpl["title"],
                            body=tmpl["body"],
                            deep_link=tmpl["deep_link"],
                        )
                        if sent:
                            continue

            except Exception as e:
                # Catch per-install failures so one bad record doesn't break the tick
                print(f"[scheduler] {install_id}: error processing install: {repr(e)}")
                continue

    except Exception as e:
        # Catch cursor-level / DB connectivity issues
        print(f"[scheduler] fatal tick error: {repr(e)}")
