from motor.motor_asyncio import AsyncIOMotorClient
from .config import settings

_client = AsyncIOMotorClient(settings.mongo_uri)
db = _client[settings.mongo_db]

installs = db["installs"]
devices = db["devices"]
prefs = db["prefs"]
events_daily = db["events_daily"]
push_log = db["push_log"]
push_jobs = db["push_jobs"]  # optional, but useful
worker_heartbeat = db["worker_heartbeat"]

async def ensure_indexes() -> None:
    await devices.create_index("install_id")
    await push_log.create_index([("install_id", 1), ("date", 1)])
