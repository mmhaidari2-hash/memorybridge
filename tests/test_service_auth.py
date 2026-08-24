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
DB_KEY_B = "mbs_database_test_key_b_bcdefghijklmnopqrstuvwxyz"

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    base64.b64encode(b"x" * 32).decode("ascii"),
)
os.environ.setdefault("SERVICE_API_KEYS", LEGACY_KEY)

from app.database import Base, get_db
from app.models import ApiKey, Tenant, UsageEvent, User, Workspace
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


def seed_database_key(*, key=DB_KEY, tenant_name="Test Tenant", workspace_slug="default", tenant_status="active", key_active=True):
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    with TestingSessionLocal() as db:
        tenant = Tenant(name=tenant_name, status=tenant_status)
        workspace = Workspace(name=workspace_slug.title(), slug=workspace_slug, tenant=tenant)
        api_key = ApiKey(
            workspace=workspace,
            name="Test key",
            key_prefix=key[:12],
            key_hash=key_hash,
            is_active=key_active,
        )
        db.add(tenant)
        db.commit()
        return tenant.id, workspace.id, api_key.id


def test_database_key_authenticates_and_updates_last_used_at():
    reset_database()
    _, workspace_id, api_key_id = seed_database_key()

    response = client.post(
        "/v1/auth/token",
        json={"full_name": "DB User"},
        headers={"X-MemoryBridge-Key": DB_KEY},
    )

    assert response.status_code == 201
    with TestingSessionLocal() as db:
        api_key = db.get(ApiKey, api_key_id)
        user = db.query(User).one()
        assert isinstance(api_key.last_used_at, datetime)
        assert user.workspace_id == workspace_id


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
    with TestingSessionLocal() as db:
        user = db.query(User).one()
        assert user.workspace_id is None
        assert db.query(UsageEvent).count() == 0


def test_workspace_b_cannot_recall_or_update_workspace_a_memory_even_with_tokens():
    reset_database()
    seed_database_key(key=DB_KEY, tenant_name="Tenant A", workspace_slug="alpha")
    seed_database_key(key=DB_KEY_B, tenant_name="Tenant B", workspace_slug="beta")

    headers_a = {"X-MemoryBridge-Key": DB_KEY}
    headers_b = {"X-MemoryBridge-Key": DB_KEY_B}

    create_a = client.post("/v1/auth/token", json={"full_name": "User A"}, headers=headers_a)
    assert create_a.status_code == 201
    user_token_a = create_a.json()["user_token"]

    store_a = client.post(
        "/v1/memory/store",
        json={"user_token": user_token_a, "summary": "Tenant A private memory"},
        headers=headers_a,
    )
    assert store_a.status_code == 201
    session_token_a = store_a.json()["session_token"]

    own_recall = client.post(
        "/v1/memory/recall",
        json={"user_token": user_token_a, "session_token": session_token_a},
        headers=headers_a,
    )
    assert own_recall.status_code == 200
    assert own_recall.json()["summary"] == "Tenant A private memory"

    cross_recall = client.post(
        "/v1/memory/recall",
        json={"user_token": user_token_a, "session_token": session_token_a},
        headers=headers_b,
    )
    assert cross_recall.status_code == 401
    assert cross_recall.json()["detail"] == "Invalid credentials"

    cross_update = client.put(
        "/v1/memory/update",
        json={
            "user_token": user_token_a,
            "session_token": session_token_a,
            "summary": "Compromised",
        },
        headers=headers_b,
    )
    assert cross_update.status_code == 401
    assert cross_update.json()["detail"] == "Invalid credentials"

    verify_unchanged = client.post(
        "/v1/memory/recall",
        json={"user_token": user_token_a, "session_token": session_token_a},
        headers=headers_a,
    )
    assert verify_unchanged.status_code == 200
    assert verify_unchanged.json()["summary"] == "Tenant A private memory"


def test_workspace_usage_events_are_recorded_for_successful_operations_only():
    reset_database()
    tenant_id, workspace_id, _ = seed_database_key()
    headers = {"X-MemoryBridge-Key": DB_KEY}

    created = client.post("/v1/auth/token", json={"full_name": "Metered User"}, headers=headers)
    assert created.status_code == 201
    user_token = created.json()["user_token"]

    stored = client.post(
        "/v1/memory/store",
        json={"user_token": user_token, "summary": "meter me"},
        headers=headers,
    )
    assert stored.status_code == 201
    session_token = stored.json()["session_token"]

    recalled = client.post(
        "/v1/memory/recall",
        json={"user_token": user_token, "session_token": session_token},
        headers=headers,
    )
    assert recalled.status_code == 200

    updated = client.put(
        "/v1/memory/update",
        json={"user_token": user_token, "session_token": session_token, "stage": "done"},
        headers=headers,
    )
    assert updated.status_code == 200

    failed = client.post(
        "/v1/memory/recall",
        json={"user_token": "mb_invalid", "session_token": session_token},
        headers=headers,
    )
    assert failed.status_code == 401

    with TestingSessionLocal() as db:
        events = db.query(UsageEvent).order_by(UsageEvent.created_at.asc()).all()
        assert [event.event_type for event in events] == [
            "user.create",
            "memory.store",
            "memory.recall",
            "memory.update",
        ]
        assert all(event.quantity == 1 for event in events)
        assert all(event.workspace_id == workspace_id for event in events)
        assert all(event.tenant_id == tenant_id for event in events)
