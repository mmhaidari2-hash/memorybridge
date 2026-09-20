"""Atomic metering: failed business writes must not burn quota."""

import os

SERVICE_API_KEY = "mbs_test_service_key_abcdefghijklmnopqrstuvwxyz"
SERVICE_HEADERS = {"X-MemoryBridge-Key": SERVICE_API_KEY}
os.environ.setdefault("SERVICE_API_KEYS", SERVICE_API_KEY)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.billing import ensure_plans
from app.config import clear_settings_cache
from app.database import Base, get_db
from app.rate_limit import rate_limiter
from main import app

clear_settings_cache()
rate_limiter.reset()

engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def reset_database():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    rate_limiter.reset()
    with TestingSessionLocal() as db:
        ensure_plans(db)


def test_conflict_store_does_not_burn_quota():
    reset_database()
    user_token = client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).json()["user_token"]
    session_token = "sess_fixed_atomic_meter_token_001"

    first = client.post(
        "/v1/memory/store",
        json={"user_token": user_token, "session_token": session_token, "summary": "one"},
        headers=SERVICE_HEADERS,
    )
    assert first.status_code == 201

    after_success = client.get("/v1/billing/status", headers=SERVICE_HEADERS)
    assert after_success.status_code == 200
    used_after_success = after_success.json()["ops_used"]

    conflict = client.post(
        "/v1/memory/store",
        json={"user_token": user_token, "session_token": session_token, "summary": "two"},
        headers=SERVICE_HEADERS,
    )
    assert conflict.status_code == 409

    after_conflict = client.get("/v1/billing/status", headers=SERVICE_HEADERS)
    assert after_conflict.status_code == 200
    # Conflict rolled back metering — ops_used must be unchanged.
    assert after_conflict.json()["ops_used"] == used_after_success
