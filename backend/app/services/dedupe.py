"""Per-day push records: dedupe claims and the daily cap.

A push_log doc (``_id`` = dedupe key) is inserted *before* a push is sent.
Mongo's unique ``_id`` makes the insert the claim: if two workers race, only
one insert succeeds. If the send then fails, the claim is released so a later
tick can retry silently. Docs expire via a TTL index on ``sent_at``.
"""

from datetime import UTC, datetime

from pymongo.errors import DuplicateKeyError

from .. import db


async def claim(dedupe_key: str, install_id: str, day: str, ntype: str) -> bool:
    """Reserve this notification. False means it was already sent (or is being sent)."""
    try:
        await db.push_log.insert_one(
            {
                "_id": dedupe_key,
                "install_id": install_id,
                "type": ntype,
                "date": day,
                "sent_at": datetime.now(UTC),
            }
        )
    except DuplicateKeyError:
        return False
    return True


async def release(dedupe_key: str) -> None:
    """Undo a claim after a failed send."""
    await db.push_log.delete_one({"_id": dedupe_key})


async def count_sent(install_id: str, day: str) -> int:
    return await db.push_log.count_documents({"install_id": install_id, "date": day})


async def sent_counts(install_ids: list[str], days: list[str]) -> dict[tuple[str, str], int]:
    """Count push_log docs per (install_id, local day) for a page of installs."""
    counts: dict[tuple[str, str], int] = {}
    cursor = db.push_log.find(
        {"install_id": {"$in": install_ids}, "date": {"$in": days}},
        {"install_id": 1, "date": 1},
    )
    async for doc in cursor:
        key = (doc["install_id"], doc["date"])
        counts[key] = counts.get(key, 0) + 1
    return counts
