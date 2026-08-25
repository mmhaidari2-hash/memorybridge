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
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))
os.environ.setdefault("SERVICE_API_KEYS", LEGACY_KEY)

from app.database import Base, get_db
from app.models import ApiKey, Tenant, UsageEvent, User, Workspace
from app.quota import PLAN_MONTHLY_EVENT_LIMITS
from app.service_auth import get_legacy_service_key_hashes
from main import app

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    os.environ["SERVICE_API_KEYS"] = LEGACY_KEY
    get_legacy_service_key_hashes.cache_clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed_database_key(*, key=DB_KEY, tenant_name="Test Tenant", workspace_slug="default", tenant_status="active", key_active=True, plan="free"):
    key_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    with TestingSessionLocal() as db:
        tenant = Tenant(name=tenant_name, status=tenant_status, plan=plan)
        workspace = Workspace(name=workspace_slug.title(), slug=workspace_slug, tenant=tenant)
        api_key = ApiKey(workspace=workspace, name="Test key", key_prefix=key[:12], key_hash=key_hash, is_active=key_active)
        db.add(tenant)
        db.commit()
        return tenant.id, workspace.id, api_key.id


def test_database_key_authenticates_and_updates_last_used_at():
    reset_database()
    _, workspace_id, api_key_id = seed_database_key()
    response = client.post("/v1/auth/token", json={"full_name": "DB User"}, headers={"X-MemoryBridge-Key": DB_KEY})
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
    response = client.post("/v1/auth/token", json={}, headers={"X-MemoryBridge-Key": DB_KEY})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid service API key"


def test_database_key_for_inactive_tenant_is_rejected():
    reset_database()
    seed_database_key(tenant_status="suspended")
    response = client.post("/v1/auth/token", json={}, headers={"X-MemoryBridge-Key": DB_KEY})
    assert response.status_code == 401


def test_legacy_environment_key_still_works_during_transition():
    reset_database()
    response = client.post("/v1/auth/token", json={"full_name": "Legacy User"}, headers={"X-MemoryBridge-Key": LEGACY_KEY})
    assert response.status_code == 201
    with TestingSessionLocal() as db:
        assert db.query(User).one().workspace_id is None
        assert db.query(UsageEvent).count() == 0


def test_workspace_b_cannot_recall_or_update_workspace_a_memory_even_with_tokens():
    reset_database()
    seed_database_key(key=DB_KEY, tenant_name="Tenant A", workspace_slug="alpha")
    seed_database_key(key=DB_KEY_B, tenant_name="Tenant B", workspace_slug="beta")
    headers_a = {"X-MemoryBridge-Key": DB_KEY}
    headers_b = {"X-MemoryBridge-Key": DB_KEY_B}
    create_a = client.post("/v1/auth/token", json={"full_name": "User A"}, headers=headers_a)
    user_token_a = create_a.json()["user_token"]
    store_a = client.post("/v1/memory/store", json={"user_token": user_token_a, "summary": "Tenant A private memory"}, headers=headers_a)
    session_token_a = store_a.json()["session_token"]
    own_recall = client.post("/v1/memory/recall", json={"user_token": user_token_a, "session_token": session_token_a}, headers=headers_a)
    assert own_recall.status_code == 200
    cross_recall = client.post("/v1/memory/recall", json={"user_token": user_token_a, "session_token": session_token_a}, headers=headers_b)
    assert cross_recall.status_code == 401
    cross_update = client.put("/v1/memory/update", json={"user_token": user_token_a, "session_token": session_token_a, "summary": "Compromised"}, headers=headers_b)
    assert cross_update.status_code == 401
    verify = client.post("/v1/memory/recall", json={"user_token": user_token_a, "session_token": session_token_a}, headers=headers_a)
    assert verify.json()["summary"] == "Tenant A private memory"


def test_workspace_usage_events_are_recorded_for_successful_operations_only():
    reset_database()
    tenant_id, workspace_id, _ = seed_database_key()
    headers = {"X-MemoryBridge-Key": DB_KEY}
    created = client.post("/v1/auth/token", json={"full_name": "Metered User"}, headers=headers)
    user_token = created.json()["user_token"]
    stored = client.post("/v1/memory/store", json={"user_token": user_token, "summary": "meter me"}, headers=headers)
    session_token = stored.json()["session_token"]
    assert client.post("/v1/memory/recall", json={"user_token": user_token, "session_token": session_token}, headers=headers).status_code == 200
    assert client.put("/v1/memory/update", json={"user_token": user_token, "session_token": session_token, "stage": "done"}, headers=headers).status_code == 200
    assert client.post("/v1/memory/recall", json={"user_token": "mb_invalid_token_1234567890", "session_token": session_token}, headers=headers).status_code == 401
    with TestingSessionLocal() as db:
        events = db.query(UsageEvent).order_by(UsageEvent.created_at.asc()).all()
        assert [e.event_type for e in events] == ["user.create", "memory.store", "memory.recall", "memory.update"]
        assert all(e.workspace_id == workspace_id and e.tenant_id == tenant_id for e in events)


def test_free_plan_allows_last_event_then_rejects_next_without_metering_it():
    reset_database()
    tenant_id, workspace_id, _ = seed_database_key(plan="free")
    limit = PLAN_MONTHLY_EVENT_LIMITS["free"]
    with TestingSessionLocal() as db:
        db.add(UsageEvent(tenant_id=tenant_id, workspace_id=workspace_id, event_type="seed", quantity=limit - 1))
        db.commit()
    headers = {"X-MemoryBridge-Key": DB_KEY}
    assert client.post("/v1/auth/token", json={"full_name": "Last Free User"}, headers=headers).status_code == 201
    rejected = client.post("/v1/auth/token", json={"full_name": "Over Quota"}, headers=headers)
    assert rejected.status_code == 429
    assert rejected.json()["detail"]["used"] == limit
    with TestingSessionLocal() as db:
        assert sum(e.quantity for e in db.query(UsageEvent).filter(UsageEvent.tenant_id == tenant_id).all()) == limit
        assert db.query(User).count() == 1


def test_pro_plan_accepts_usage_above_free_limit():
    reset_database()
    tenant_id, workspace_id, _ = seed_database_key(plan="pro")
    free_limit = PLAN_MONTHLY_EVENT_LIMITS["free"]
    with TestingSessionLocal() as db:
        db.add(UsageEvent(tenant_id=tenant_id, workspace_id=workspace_id, event_type="seed", quantity=free_limit))
        db.commit()
    assert client.post("/v1/auth/token", json={"full_name": "Paid User"}, headers={"X-MemoryBridge-Key": DB_KEY}).status_code == 201


def test_api_key_create_list_revoke_and_plaintext_is_returned_once():
    reset_database()
    _, workspace_id, root_key_id = seed_database_key()
    headers = {"X-MemoryBridge-Key": DB_KEY}
    created = client.post("/v1/api-keys", json={"name": "Production"}, headers=headers)
    assert created.status_code == 201
    body = created.json()
    plaintext = body["api_key"]
    assert plaintext.startswith("mbs_")
    assert body["key_prefix"] == plaintext[:12]
    with TestingSessionLocal() as db:
        stored = db.get(ApiKey, body["id"])
        assert stored.workspace_id == workspace_id
        assert stored.key_hash == hashlib.sha256(plaintext.encode("utf-8")).hexdigest()
        assert plaintext not in stored.key_hash
    listed = client.get("/v1/api-keys", headers=headers)
    assert listed.status_code == 200
    listed_body = listed.json()
    assert len(listed_body) == 2
    assert all("api_key" not in item for item in listed_body)
    assert {item["id"] for item in listed_body} == {root_key_id, body["id"]}
    revoked = client.delete(f"/v1/api-keys/{body['id']}", headers=headers)
    assert revoked.status_code == 204
    assert client.post("/v1/auth/token", json={}, headers={"X-MemoryBridge-Key": plaintext}).status_code == 401


def test_workspace_cannot_list_or_revoke_another_workspace_key():
    reset_database()
    _, _, key_a_id = seed_database_key(key=DB_KEY, tenant_name="Tenant A", workspace_slug="alpha")
    _, _, key_b_id = seed_database_key(key=DB_KEY_B, tenant_name="Tenant B", workspace_slug="beta")
    headers_a = {"X-MemoryBridge-Key": DB_KEY}
    listed = client.get("/v1/api-keys", headers=headers_a)
    assert listed.status_code == 200
    assert {item["id"] for item in listed.json()} == {key_a_id}
    assert client.delete(f"/v1/api-keys/{key_b_id}", headers=headers_a).status_code == 404
    assert client.post("/v1/auth/token", json={}, headers={"X-MemoryBridge-Key": DB_KEY_B}).status_code == 201


def test_legacy_key_cannot_manage_workspace_keys():
    reset_database()
    assert client.post("/v1/api-keys", json={"name": "Nope"}, headers={"X-MemoryBridge-Key": LEGACY_KEY}).status_code == 403
    assert client.get("/v1/api-keys", headers={"X-MemoryBridge-Key": LEGACY_KEY}).status_code == 403


def test_account_status_exposes_free_upgrade_state_and_usage_percent():
    reset_database()
    tenant_id, workspace_id, _ = seed_database_key(plan="free")
    with TestingSessionLocal() as db:
        db.add(UsageEvent(tenant_id=tenant_id, workspace_id=workspace_id, event_type="seed", quantity=250))
        db.commit()

    response = client.get("/v1/account/status", headers={"X-MemoryBridge-Key": DB_KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "free"
    assert body["can_upgrade"] is True
    assert body["paid_entitlement_active"] is False
    assert body["usage_used"] == 250
    assert body["usage_limit"] == PLAN_MONTHLY_EVENT_LIMITS["free"]
    assert body["usage_remaining"] == PLAN_MONTHLY_EVENT_LIMITS["free"] - 250
    assert body["usage_percent"] == 25.0


def test_account_status_marks_verified_paid_entitlement_active():
    reset_database()
    tenant_id, _, _ = seed_database_key(plan="pro")
    with TestingSessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        tenant.subscription_status = "active"
        db.commit()

    response = client.get("/v1/account/status", headers={"X-MemoryBridge-Key": DB_KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["plan"] == "pro"
    assert body["subscription_status"] == "active"
    assert body["paid_entitlement_active"] is True
    assert body["can_upgrade"] is False


def test_account_status_does_not_treat_unverified_pro_state_as_active_paid_entitlement():
    reset_database()
    tenant_id, _, _ = seed_database_key(plan="pro")
    with TestingSessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        tenant.subscription_status = "canceled"
        db.commit()

    response = client.get("/v1/account/status", headers={"X-MemoryBridge-Key": DB_KEY})
    assert response.status_code == 200
    body = response.json()
    assert body["paid_entitlement_active"] is False
    assert body["can_upgrade"] is False
