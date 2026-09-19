import base64
import os

SERVICE_API_KEY = "mbs_test_service_key_abcdefghijklmnopqrstuvwxyz"
ADMIN_API_KEY = "mba_test_admin_key_abcdefghijklmnopqrstuvwxyz012345"
SERVICE_HEADERS = {"X-MemoryBridge-Key": SERVICE_API_KEY}
ADMIN_HEADERS = {"X-MemoryBridge-Admin-Key": ADMIN_API_KEY}

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))
os.environ.setdefault("SERVICE_API_KEYS", SERVICE_API_KEY)
os.environ.setdefault("ADMIN_API_KEY", ADMIN_API_KEY)
os.environ.setdefault("TOKEN_HASH_PEPPER", base64.b64encode(b"p" * 32).decode("ascii"))
os.environ.setdefault("RATE_LIMIT_REQUESTS", "1000")
os.environ.setdefault("RATE_LIMIT_WINDOW_SECONDS", "60")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import clear_settings_cache
from app.database import Base, get_db
from app.models import AuditEvent, MemoryRecord, User
from app.rate_limit import rate_limiter
from app.security import hash_token
from main import app

clear_settings_cache()
rate_limiter.reset()

TEST_DATABASE_URL = "sqlite://"
engine = create_engine(
    TEST_DATABASE_URL,
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


def assert_security_headers(response):
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["permissions-policy"] == "camera=(), microphone=(), geolocation=()"
    assert response.headers["cache-control"] == "no-store"


def test_health_is_public_and_has_security_headers():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert_security_headers(response)


def test_readiness_checks_database_and_has_security_headers():
    reset_database()
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert_security_headers(response)


def test_v1_requires_service_api_key():
    response = client.post("/v1/auth/token", json={"full_name": "Blocked"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing service API key"
    assert_security_headers(response)


def test_v1_rejects_invalid_service_api_key():
    response = client.post(
        "/v1/auth/token",
        json={"full_name": "Blocked"},
        headers={"X-MemoryBridge-Key": "invalid-service-key-xxxxxxxxxxxx"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid service API key"


def test_create_store_recall_update_delete_flow_and_hashes_credentials():
    reset_database()

    create_response = client.post(
        "/v1/auth/token",
        json={"full_name": "Test User"},
        headers=SERVICE_HEADERS,
    )
    assert create_response.status_code == 201
    user_token = create_response.json()["user_token"]
    assert user_token.startswith("mb_")

    store_response = client.post(
        "/v1/memory/store",
        json={
            "user_token": user_token,
            "stage": "onboarding",
            "summary": "First encrypted memory",
        },
        headers=SERVICE_HEADERS,
    )
    assert store_response.status_code == 201
    session_token = store_response.json()["session_token"]
    assert session_token.startswith("sess_")

    with TestingSessionLocal() as db:
        user = db.query(User).one()
        memory = db.query(MemoryRecord).one()
        assert user.tenant_id
        assert user.user_token_hash == hash_token(user_token)
        assert user_token not in user.user_token_hash
        assert memory.session_token_hash == hash_token(session_token)
        assert session_token not in memory.session_token_hash
        assert memory.encrypted_content != "First encrypted memory"
        assert memory.key_version == 1
        assert db.query(AuditEvent).filter(AuditEvent.action == "memory.store").count() == 1

    recall_response = client.post(
        "/v1/memory/recall",
        json={"user_token": user_token, "session_token": session_token},
        headers=SERVICE_HEADERS,
    )
    assert recall_response.status_code == 200
    assert recall_response.json()["summary"] == "First encrypted memory"

    update_response = client.put(
        "/v1/memory/update",
        json={
            "user_token": user_token,
            "session_token": session_token,
            "stage": "active",
            "summary": "Updated encrypted memory",
        },
        headers=SERVICE_HEADERS,
    )
    assert update_response.status_code == 200
    assert update_response.json()["summary"] == "Updated encrypted memory"
    assert update_response.json()["stage"] == "active"

    list_response = client.post(
        "/v1/memory/list",
        json={"user_token": user_token},
        headers=SERVICE_HEADERS,
    )
    assert list_response.status_code == 200
    assert len(list_response.json()["sessions"]) == 1
    assert "summary" not in list_response.json()["sessions"][0]

    delete_response = client.post(
        "/v1/memory/delete",
        json={"user_token": user_token, "session_token": session_token},
        headers=SERVICE_HEADERS,
    )
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted"] is True

    missing = client.post(
        "/v1/memory/recall",
        json={"user_token": user_token, "session_token": session_token},
        headers=SERVICE_HEADERS,
    )
    assert missing.status_code == 404


def test_duplicate_session_store_is_conflict():
    reset_database()
    user_token = client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).json()["user_token"]
    session_token = "sess_fixed_session_token_abc123"
    first = client.post(
        "/v1/memory/store",
        json={"user_token": user_token, "session_token": session_token, "summary": "one"},
        headers=SERVICE_HEADERS,
    )
    second = client.post(
        "/v1/memory/store",
        json={"user_token": user_token, "session_token": session_token, "summary": "two"},
        headers=SERVICE_HEADERS,
    )
    assert first.status_code == 201
    assert second.status_code == 409


def test_invalid_user_token_is_rejected_without_user_enumeration():
    reset_database()

    response = client.post(
        "/v1/memory/store",
        json={
            "user_token": "mb_invalid_token_1234567890",
            "summary": "should fail",
        },
        headers=SERVICE_HEADERS,
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_cross_user_session_access_is_blocked():
    reset_database()

    user_a = client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).json()["user_token"]
    user_b = client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS).json()["user_token"]

    session_token = client.post(
        "/v1/memory/store",
        json={"user_token": user_a, "summary": "A private memory"},
        headers=SERVICE_HEADERS,
    ).json()["session_token"]

    response = client.post(
        "/v1/memory/recall",
        json={"user_token": user_b, "session_token": session_token},
        headers=SERVICE_HEADERS,
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Memory session not found"


def test_tenant_isolation_and_key_revocation():
    reset_database()

    tenant = client.post(
        "/v1/admin/tenants",
        json={"name": "Acme AI", "slug": "acme-ai"},
        headers=ADMIN_HEADERS,
    )
    assert tenant.status_code == 201
    tenant_id = tenant.json()["id"]

    key = client.post(
        f"/v1/admin/tenants/{tenant_id}/keys",
        json={"name": "production"},
        headers=ADMIN_HEADERS,
    )
    assert key.status_code == 201
    tenant_key = key.json()["api_key"]
    key_id = key.json()["id"]
    tenant_headers = {"X-MemoryBridge-Key": tenant_key}

    user_token = client.post(
        "/v1/auth/token",
        json={"full_name": "Acme User"},
        headers=tenant_headers,
    ).json()["user_token"]

    session_token = client.post(
        "/v1/memory/store",
        json={"user_token": user_token, "summary": "tenant secret"},
        headers=tenant_headers,
    ).json()["session_token"]

    # Default env key must not see the other tenant's user.
    cross = client.post(
        "/v1/memory/recall",
        json={"user_token": user_token, "session_token": session_token},
        headers=SERVICE_HEADERS,
    )
    assert cross.status_code == 401

    # Revoke key → subsequent calls fail.
    revoked = client.post(f"/v1/admin/keys/{key_id}/revoke", headers=ADMIN_HEADERS)
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"

    after_revoke = client.post(
        "/v1/memory/recall",
        json={"user_token": user_token, "session_token": session_token},
        headers=tenant_headers,
    )
    assert after_revoke.status_code == 401


def test_suspended_tenant_cannot_authenticate():
    reset_database()

    tenant = client.post(
        "/v1/admin/tenants",
        json={"name": "Paused Co", "slug": "paused-co"},
        headers=ADMIN_HEADERS,
    ).json()
    key = client.post(
        f"/v1/admin/tenants/{tenant['id']}/keys",
        json={"name": "prod"},
        headers=ADMIN_HEADERS,
    ).json()

    suspend = client.post(
        f"/v1/admin/tenants/{tenant['id']}/suspend",
        headers=ADMIN_HEADERS,
    )
    assert suspend.status_code == 200
    assert suspend.json()["status"] == "suspended"

    blocked = client.post(
        "/v1/auth/token",
        json={},
        headers={"X-MemoryBridge-Key": key["api_key"]},
    )
    assert blocked.status_code == 403


def test_admin_routes_require_admin_key():
    reset_database()
    response = client.post("/v1/admin/tenants", json={"name": "X", "slug": "x-co"})
    assert response.status_code == 401


def test_metrics_endpoint_exposes_counters():
    reset_database()
    client.post("/v1/auth/token", json={}, headers=SERVICE_HEADERS)
    response = client.get("/metrics")
    assert response.status_code == 200
    assert "memorybridge_requests_total" in response.text


def test_request_size_limit_middleware_rejects_large_content_length():
    from app.request_limits import RequestSizeLimitMiddleware
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient as StarletteClient

    async def ok(_request):
        return PlainTextResponse("ok")

    mini = Starlette(routes=[Route("/", ok, methods=["POST"])])
    mini.add_middleware(RequestSizeLimitMiddleware)
    mini_client = StarletteClient(mini)
    response = mini_client.post("/", content=b"tiny", headers={"Content-Length": "9999999"})
    assert response.status_code == 413
