"""The worker's periodic tick: decide which installs get a push right now.

Per tick, installs with push enabled are read in pages. For each page, prefs,
devices, today's event rollups and today's push counts are loaded with one
``$in`` query each, instead of several queries per install.

"Today" always means the install's local calendar date (its timezone), for the
daily cap, dedupe keys and event rollups alike.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from .. import db
from . import dedupe
from .apns import APNSTokenInvalid, send_alert
from .defaults import (
    DEFAULT_DAILY_CHECKIN,
    DEFAULT_MAX_PUSH_PER_DAY,
    DEFAULT_QUIET_HOURS,
    DEFAULT_TIMEZONE,
)
from .notifications import NOTIFICATION_TEMPLATES, dedupe_key
from .rules import (
    should_send_capture_sort_nudge,
    should_send_daily_checkin,
    should_send_focus_first_step_nudge,
)
from .timeutils import as_utc, in_quiet_hours, local_day, zone_or_utc

logger = logging.getLogger("withyou.scheduler")

INSTALL_PAGE_SIZE = 200

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

# Outcomes of one send attempt
SENT = "sent"
DUPLICATE = "duplicate"  # already sent (or being sent) for this local day
CAPPED = "capped"  # daily cap reached
FAILED = "failed"  # not delivered; a later tick may retry silently


@dataclass
class _InstallNow:
    install_id: str
    prefs: dict[str, Any]
    local_dt: datetime
    day: str


async def tick(now_utc: datetime | None = None) -> None:
    now_utc = now_utc or datetime.now(UTC)
    logger.info("tick ran at %s", now_utc.isoformat())

    # Heartbeat is operational telemetry only; do not fail tick if it cannot be written.
    try:
        await db.worker_heartbeat.update_one(
            {"_id": "scheduler"},
            {"$set": {"last_tick_at": now_utc}},
            upsert=True,
        )
    except Exception:
        logger.warning("heartbeat write failed", exc_info=True)

    try:
        last_id = None
        while True:
            query: dict[str, Any] = {"push_enabled": True}
            if last_id is not None:
                query["_id"] = {"$gt": last_id}
            cursor = db.installs.find(query, {"timezone": 1}).sort("_id", 1).limit(INSTALL_PAGE_SIZE)
            page = await cursor.to_list(INSTALL_PAGE_SIZE)
            if not page:
                break
            await _process_page(page, now_utc)
            if len(page) < INSTALL_PAGE_SIZE:
                break
            last_id = page[-1]["_id"]
    except Exception:
        # Cursor-level / DB connectivity issues
        logger.exception("fatal tick error")


async def _process_page(page: list[dict[str, Any]], now_utc: datetime) -> None:
    install_ids = [inst["_id"] for inst in page]
    prefs_by_id = {doc["_id"]: doc async for doc in db.prefs.find({"_id": {"$in": install_ids}})}

    # Cheap, per-install checks first, so the remaining queries only cover
    # installs that might actually get a push this tick.
    active: list[_InstallNow] = []
    for inst in page:
        install_id = inst["_id"]
        p = prefs_by_id.get(install_id)
        if not p:
            # No prefs saved: the user has not opted into anything yet.
            continue
        try:
            tz = zone_or_utc(inst.get("timezone") or DEFAULT_TIMEZONE)
            local_dt = now_utc.astimezone(tz)
            qh = p.get("quiet_hours") or DEFAULT_QUIET_HOURS
            if in_quiet_hours(local_dt, qh["start"], qh["end"]):
                continue
            active.append(_InstallNow(install_id, p, local_dt, local_day(now_utc, tz)))
        except Exception:
            logger.exception("%s: error processing install", install_id)

    if not active:
        return

    active_ids = [a.install_id for a in active]
    days = sorted({a.day for a in active})

    device_by_install: dict[str, dict[str, Any]] = {}
    async for dev in db.devices.find({"install_id": {"$in": active_ids}}):
        current = device_by_install.get(dev["install_id"])
        if current is None or _device_updated_at(dev) > _device_updated_at(current):
            device_by_install[dev["install_id"]] = dev

    agg_ids = [f"{a.install_id}|{a.day}" for a in active]
    agg_by_id = {doc["_id"]: doc async for doc in db.events_daily.find({"_id": {"$in": agg_ids}})}

    sent_counts = await dedupe.sent_counts(active_ids, days)

    for a in active:
        try:
            await _process_install(
                a,
                device=device_by_install.get(a.install_id),
                agg=agg_by_id.get(f"{a.install_id}|{a.day}") or {},
                sent_today=sent_counts.get((a.install_id, a.day), 0),
                now_utc=now_utc,
            )
        except Exception:
            # One bad record must not break the tick for everyone else
            logger.exception("%s: error processing install", a.install_id)


def _device_updated_at(dev: dict[str, Any]) -> datetime:
    updated_at = dev.get("updated_at")
    return as_utc(updated_at) if isinstance(updated_at, datetime) else _EPOCH


async def _process_install(
    a: _InstallNow,
    device: dict[str, Any] | None,
    agg: dict[str, Any],
    sent_today: int,
    now_utc: datetime,
) -> None:
    max_per_day = int(a.prefs.get("max_push_per_day", DEFAULT_MAX_PUSH_PER_DAY))
    if sent_today >= max_per_day:
        return
    if device is None:
        return

    for ntype in _due_notifications(a, agg, now_utc):
        result = await _send_once(a, ntype, device, max_per_day)
        if result != DUPLICATE:
            # At most one push per install per tick. After a failure, wait for
            # a later tick rather than trying the next notification type.
            return


def _due_notifications(a: _InstallNow, agg: dict[str, Any], now_utc: datetime) -> list[str]:
    """Notification types that are due now, in priority order."""
    p = a.prefs
    due: list[str] = []

    dc = p.get("daily_checkin") or DEFAULT_DAILY_CHECKIN
    if should_send_daily_checkin(
        a.local_dt,
        bool(dc.get("enabled")),
        dc.get("time", DEFAULT_DAILY_CHECKIN["time"]),
    ):
        due.append("daily_checkin")

    # Opt-in only (see DEFAULT_FOCUS_NUDGES): this nudge lands during a focus session.
    if (p.get("focus_nudges") or {}).get("enabled", False) and should_send_focus_first_step_nudge(
        now_utc,
        agg.get("focus_started_at"),
        bool(agg.get("focus_first_step_set", False)),
    ):
        due.append("focus_first_step")

    if (p.get("capture_nudges") or {}).get("enabled", False) and should_send_capture_sort_nudge(
        int(agg.get("captures_count", 0))
    ):
        due.append("capture_sort")

    return due


async def _send_once(a: _InstallNow, ntype: str, device: dict[str, Any], max_per_day: int) -> str:
    key = dedupe_key(a.install_id, a.day, ntype)

    # Claim first: the insert either wins or this was already sent today.
    if not await dedupe.claim(key, a.install_id, a.day, ntype):
        return DUPLICATE

    # The cap was checked against a snapshot taken before this claim; recount
    # so concurrent claims for other types cannot push the day over the cap.
    if await dedupe.count_sent(a.install_id, a.day) > max_per_day:
        await dedupe.release(key)
        return CAPPED

    token = device["_id"]
    tmpl = NOTIFICATION_TEMPLATES[ntype]
    try:
        await send_alert(
            token,
            tmpl["title"],
            tmpl["body"],
            deep_link=tmpl["deep_link"],
            apns_environment=device.get("apns_environment"),
        )
    except APNSTokenInvalid as e:
        await dedupe.release(key)
        await db.devices.delete_one({"_id": token})
        logger.warning("%s: removed invalid token: %r", a.install_id, e)
        return FAILED
    except httpx.ReadTimeout:
        # The request may have reached APNs. Keep the claim: a missed nudge is
        # better than a duplicate one.
        logger.warning("%s: APNs timeout for %s; not retrying today", a.install_id, ntype)
        return FAILED
    except Exception as e:
        # Not delivered: release the claim so a later tick can retry silently.
        await dedupe.release(key)
        logger.warning("%s: APNs error for %s: %r", a.install_id, ntype, e)
        return FAILED

    logger.info("%s: sent %s", a.install_id, ntype)
    return SENT
