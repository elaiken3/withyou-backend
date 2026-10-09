"""Mongo client and collection handles.

Other modules access collections as attributes of this module (``db.installs``)
rather than importing the names directly, so tests can swap in an in-memory
database by patching the attributes here.

Follow-up: Motor is deprecated in favour of PyMongo's native async API
(``pymongo.AsyncMongoClient``). Migrating is a mechanical change contained to
this module and a few call sites, but it is intentionally not done yet.
"""

import certifi
from motor.motor_asyncio import AsyncIOMotorClient

from .config import settings

# Short-lived derived data only: push dedupe/cap records and daily event rollups
# are removed automatically by Mongo TTL indexes after this long.
PUSH_LOG_RETENTION_SECONDS = 35 * 24 * 60 * 60
EVENTS_DAILY_RETENTION_SECONDS = 35 * 24 * 60 * 60

client = AsyncIOMotorClient(settings.mongo_uri, tlsCAFile=certifi.where())
database = client[settings.mongo_db]

installs = database["installs"]
devices = database["devices"]
prefs = database["prefs"]
events_daily = database["events_daily"]
push_log = database["push_log"]
worker_heartbeat = database["worker_heartbeat"]


async def ensure_indexes() -> None:
    await installs.create_index([("push_enabled", 1), ("_id", 1)])
    await devices.create_index("install_id")
    await push_log.create_index([("install_id", 1), ("date", 1)])
    await push_log.create_index("sent_at", expireAfterSeconds=PUSH_LOG_RETENTION_SECONDS)
    await events_daily.create_index("install_id")
    await events_daily.create_index("updated_at", expireAfterSeconds=EVENTS_DAILY_RETENTION_SECONDS)
