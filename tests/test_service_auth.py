import base64
import hashlib
import os
from datetime import datetime

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

LEGACY_KEY = "mbs_legacy_test_key_abcdefghijklmnopqrstuvwxyz"
DB_KEY = "mbs_database_test_key_abcdefghijklmnopqrstuvwxyz"

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    base64.b64encode(b"x" * 32).decode("ascii"),
)
os.environ.setdefault("SERVICE_API_KEYS", LEGACY_KEY)

from app.database import Base, get_db
from app.models import ApiKey, Tenant, Workspace
from app.service_auth import get_legacy_service_key_hashes
from main import app

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
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    get_legacy_service_key_hashes.cache_clear()


def seed_database_key(*, tenant_status="active", key_active=True):
    key_hash = hashlib.sha256(DB_KEY.encode("utf-8")).hexdigest()
    with TestingSessionLocal() as db:
        tenant = Tenant(name="Test Tenant", status=tenant_status)
        workspace = Workspace(name="Default", slug="default", tenant=tenant)
        api_key = ApiKey(
            workspace=workspace,
            name="Test key",
            key_prefix=DB_KEY[:12],
            key_hash=key_hash,
            is_active=key_active,
        )
        db.add(tenant)
        db.commit()
        return tenant.id, workspace.id, api_key.id


def test_database_key_authenticates_and_updates_last_used_at():
    reset_database()
    _, _, api_key_id = seed_database_key()

    response = client.post(
        "/v1/auth/token",
        json={"full_name": "DB User"},
        headers={"X-MemoryBridge-Key": DB_KEY},
    )

    assert response.status_code == 201
    with TestingSessionLocal() as db:
        api_key = db.get(ApiKey, api_key_id)
        assert isinstance(api_key.last_used_at, datetime)


def test_revoked_database_key_is_rejected():
    reset_database()
    _, _, api_key_id = seed_database_key()

    with TestingSessionLocal() as db:
        api_key = db.get(ApiKey, api_key_id)
        api_key.is_active = False
        api_key.revoked_at = datetime.utcnow()
        db.commit()

    response = client.post(
        "/v1/auth/token",
        json={},
        headers={"X-MemoryBridge-Key": DB_KEY},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid service API key"


def test_database_key_for_inactive_tenant_is_rejected():
    reset_database()
    seed_database_key(tenant_status="suspended")

    response = client.post(
        "/v1/auth/token",
        json={},
        headers={"X-MemoryBridge-Key": DB_KEY},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid service API key"


def test_legacy_environment_key_still_works_during_transition():
    reset_database()

    response = client.post(
        "/v1/auth/token",
        json={"full_name": "Legacy User"},
        headers={"X-MemoryBridge-Key": LEGACY_KEY},
    )

    assert response.status_code == 201
