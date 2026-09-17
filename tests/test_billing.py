import os

SERVICE_API_KEY = "mbs_test_service_key_abcdefghijklmnopqrstuvwxyz"
ADMIN_API_KEY = "mba_test_admin_key_abcdefghijklmnopqrstuvwxyz012345"
SERVICE_HEADERS = {"X-MemoryBridge-Key": SERVICE_API_KEY}
ADMIN_HEADERS = {"X-MemoryBridge-Admin-Key": ADMIN_API_KEY}

os.environ.setdefault("SERVICE_API_KEYS", SERVICE_API_KEY)
os.environ.setdefault("ADMIN_API_KEY", ADMIN_API_KEY)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.billing import ensure_plans
from app.config import clear_settings_cache
from app.database import Base, get_db
from app.models import Plan
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


def test_public_plans_and_billing_status():
    reset_database()
    plans = client.get("/v1/billing/plans")
    assert plans.status_code == 200
    codes = {p["code"] for p in plans.json()}
    assert codes == {"free", "starter", "growth"}

    assert client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).status_code == 201

    status = client.get("/v1/billing/status", headers=SERVICE_HEADERS)
    assert status.status_code == 200
    body = status.json()
    assert body["plan_code"] == "free"
    assert body["ops_used"] >= 1
    assert body["ops_remaining"] < body["ops_limit"]


def test_ops_quota_returns_402_and_blocks_api():
    reset_database()
    with TestingSessionLocal() as db:
        ensure_plans(db)
        free = db.query(Plan).filter(Plan.code == "free").one()
        free.monthly_ops_limit = 2
        free.max_memories = 100
        db.add(free)
        db.commit()

    assert client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).status_code == 201
    assert client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).status_code == 201

    blocked = client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS)
    assert blocked.status_code == 402
    detail = blocked.json()["detail"]
    assert detail["error"] == "ops_quota_exceeded"
    assert detail["upgrade"] == "/v1/billing/checkout"


def test_memory_quota_returns_402():
    reset_database()
    with TestingSessionLocal() as db:
        ensure_plans(db)
        free = db.query(Plan).filter(Plan.code == "free").one()
        free.monthly_ops_limit = 1000
        free.max_memories = 1
        db.add(free)
        db.commit()

    user = client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).json()["user_token"]
    first = client.post(
        "/v1/memory/store",
        json={"user_token": user, "summary": "one"},
        headers=SERVICE_HEADERS,
    )
    assert first.status_code == 201

    second = client.post(
        "/v1/memory/store",
        json={"user_token": user, "summary": "two"},
        headers=SERVICE_HEADERS,
    )
    assert second.status_code == 402
    assert second.json()["detail"]["error"] == "memory_quota_exceeded"


def test_admin_can_upgrade_plan_offline():
    reset_database()
    tenant = client.post(
        "/v1/admin/tenants",
        json={"name": "Paid Co", "slug": "paid-co"},
        headers=ADMIN_HEADERS,
    ).json()

    upgraded = client.post(
        f"/v1/admin/tenants/{tenant['id']}/plan",
        json={"plan_code": "starter"},
        headers=ADMIN_HEADERS,
    )
    assert upgraded.status_code == 200
    assert upgraded.json()["plan_code"] == "starter"
    assert upgraded.json()["ops_limit"] == 50_000


def test_checkout_requires_stripe_configuration():
    reset_database()
    client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS)
    response = client.post(
        "/v1/billing/checkout",
        json={"plan_code": "starter", "customer_email": "buyer@example.com"},
        headers=SERVICE_HEADERS,
    )
    assert response.status_code == 503
