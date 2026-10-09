import os

import pytest
from mongomock_motor import AsyncMongoMockClient

# Settings() needs MONGO_URI at import time. Tests never contact a real Mongo:
# the fake_db fixture swaps every collection for an in-memory one.
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")

COLLECTIONS = ("installs", "devices", "prefs", "events_daily", "push_log", "worker_heartbeat")


@pytest.fixture(autouse=True)
def no_api_key(monkeypatch):
    from backend.app.config import settings

    monkeypatch.setattr(settings, "api_key", None)


@pytest.fixture
def fake_db(monkeypatch):
    from backend.app import db

    client = AsyncMongoMockClient()
    database = client["withyou_test"]
    monkeypatch.setattr(db, "client", client)
    monkeypatch.setattr(db, "database", database)
    for name in COLLECTIONS:
        monkeypatch.setattr(db, name, database[name])
    return database


@pytest.fixture
def client(fake_db):
    from fastapi.testclient import TestClient

    from backend.app.main import app

    return TestClient(app)
