"""Tenant soft-delete keeps audit FK integrity without hard DELETE."""

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
from app.models import AuditEvent, Tenant
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


def test_soft_delete_keeps_tenant_row_and_audit_events():
    reset_database()
    created = client.post(
        "/v1/admin/tenants",
        json={"name": "Soft Co", "slug": "soft-co"},
        headers=ADMIN_HEADERS,
    )
    assert created.status_code == 201
    tenant_id = created.json()["id"]

    deleted = client.post(f"/v1/admin/tenants/{tenant_id}/delete", headers=ADMIN_HEADERS)
    assert deleted.status_code == 200
    body = deleted.json()
    assert body["status"] == "deleted"
    assert body["deleted_at"] is not None

    with TestingSessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_id).one()
        assert tenant.status == "deleted"
        assert tenant.deleted_at is not None
        audits = db.query(AuditEvent).filter(AuditEvent.tenant_id == tenant_id).all()
        assert len(audits) >= 1
        assert any(a.action == "admin.tenant_soft_delete" for a in audits)
