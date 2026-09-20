"""Autonomous audit, suspend key invalidation, and soft-delete slug reuse."""

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
from app.database import Base, get_db, set_session_factory
from app.models import AuditEvent, ServiceApiKey, Tenant
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

set_session_factory(TestingSessionLocal)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def reset_database():
    set_session_factory(TestingSessionLocal)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    rate_limiter.reset()
    with TestingSessionLocal() as db:
        ensure_plans(db)


def test_conflict_store_persists_audit_after_rollback():
    reset_database()
    user_token = client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).json()["user_token"]
    session_token = "sess_audit_conflict_token_001"
    assert (
        client.post(
            "/v1/memory/store",
            json={"user_token": user_token, "session_token": session_token, "summary": "one"},
            headers=SERVICE_HEADERS,
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/memory/store",
            json={"user_token": user_token, "session_token": session_token, "summary": "two"},
            headers=SERVICE_HEADERS,
        ).status_code
        == 409
    )

    with TestingSessionLocal() as db:
        conflicts = (
            db.query(AuditEvent)
            .filter(
                AuditEvent.action == "memory.store",
                AuditEvent.outcome == "conflict",
            )
            .all()
        )
        assert len(conflicts) == 1


def test_suspend_invalidates_api_keys():
    reset_database()
    tenant = client.post(
        "/v1/admin/tenants",
        json={"name": "Suspend Co", "slug": "suspend-co"},
        headers=ADMIN_HEADERS,
    ).json()
    key = client.post(
        f"/v1/admin/tenants/{tenant['id']}/keys",
        json={"name": "prod"},
        headers=ADMIN_HEADERS,
    ).json()
    tenant_headers = {"X-MemoryBridge-Key": key["api_key"]}

    assert client.post("/v1/auth/token", json={}, headers=tenant_headers).status_code == 201

    suspended = client.post(f"/v1/admin/tenants/{tenant['id']}/suspend", headers=ADMIN_HEADERS)
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"

    blocked = client.post("/v1/auth/token", json={}, headers=tenant_headers)
    assert blocked.status_code in {401, 403}

    with TestingSessionLocal() as db:
        db_key = db.query(ServiceApiKey).filter(ServiceApiKey.id == key["id"]).one()
        assert db_key.status == "suspended"


def test_soft_delete_frees_slug_for_reregistration():
    reset_database()
    first = client.post(
        "/v1/admin/tenants",
        json={"name": "Brand Co", "slug": "brand-co"},
        headers=ADMIN_HEADERS,
    )
    assert first.status_code == 201
    tenant_id = first.json()["id"]

    deleted = client.post(f"/v1/admin/tenants/{tenant_id}/delete", headers=ADMIN_HEADERS)
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["slug"].startswith("brand-co-deleted-")

    again = client.post(
        "/v1/admin/tenants",
        json={"name": "Brand Co Again", "slug": "brand-co"},
        headers=ADMIN_HEADERS,
    )
    assert again.status_code == 201
    assert again.json()["slug"] == "brand-co"

    with TestingSessionLocal() as db:
        assert db.query(Tenant).filter(Tenant.slug == "brand-co").count() == 1
        assert db.query(Tenant).filter(Tenant.id == tenant_id).one().status == "deleted"
