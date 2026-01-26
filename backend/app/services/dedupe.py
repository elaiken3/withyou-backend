from datetime import datetime, timezone
from ..db import push_log

async def can_send_today(install_id: str, day: str, max_per_day: int) -> bool:
    count = await push_log.count_documents({"install_id": install_id, "date": day})
    return count < max_per_day

async def already_sent(dedupe_key: str) -> bool:
    doc = await push_log.find_one({"_id": dedupe_key})
    return doc is not None

async def mark_sent(dedupe_key: str, install_id: str, day: str, ntype: str):
    await push_log.update_one(
        {"_id": dedupe_key},
        {"$setOnInsert": {
            "install_id": install_id,
            "type": ntype,
            "date": day,
            "sent_at": datetime.now(timezone.utc)
        }},
        upsert=True
    )
