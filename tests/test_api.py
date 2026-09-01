import base64
import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

SERVICE_API_KEY = "mbs_test_service_key_abcdefghijklmnopqrstuvwxyz"
SERVICE_HEADERS = {"X-MemoryBridge-Key": SERVICE_API_KEY}

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault(
    "ENCRYPTION_KEY",
    base64.b64encode(b"x" * 32).decode("ascii"),
)
os.environ.setdefault("SERVICE_API_KEYS", SERVICE_API_KEY)

from app.database import Base, get_db
from app.models import MemoryRecord, User
from app.security import hash_token
from app.service_auth import get_legacy_service_key_hashes
from main import app

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
    os.environ["SERVICE_API_KEYS"] = SERVICE_API_KEY
    get_legacy_service_key_hashes.cache_clear()
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


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
    app.dependency_overrides[get_db] = override_get_db
    response = client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}
    assert_security_headers(response)


def test_v1_requires_service_api_key():
    reset_database()
    response = client.post("/v1/auth/token", json={"full_name": "Blocked"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing service API key"
    assert_security_headers(response)


def test_v1_rejects_invalid_service_api_key():
    reset_database()
    response = client.post(
        "/v1/auth/token",
        json={"full_name": "Blocked"},
        headers={"X-MemoryBridge-Key": "invalid-service-key"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid service API key"


def test_create_store_recall_update_flow_and_hashes_credentials():
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
        assert user.user_token_hash == hash_token(user_token)
        assert user_token not in user.user_token_hash
        assert memory.session_token_hash == hash_token(session_token)
        assert session_token not in memory.session_token_hash
        assert memory.encrypted_content != "First encrypted memory"

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
