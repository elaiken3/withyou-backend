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
