import base64
import hashlib
import os
from types import SimpleNamespace

import stripe
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

LEGACY_KEY = "mbs_legacy_checkout_key_abcdefghijklmnopqrstuvwxyz"

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))
os.environ.setdefault("SERVICE_API_KEYS", LEGACY_KEY)

from app.database import Base, get_db
from app.models import ApiKey, BillingEvent, Tenant, Workspace
from app.service_auth import get_legacy_service_key_hashes
from main import app
import routers.billing as billing_router

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

SUCCESS_URL = "https://YOUR-STAGING-HOST/app/dashboard.html?billing=success"
CANCEL_URL = "https://YOUR-STAGING-HOST/app/dashboard.html?billing=cancel"
PRICE_PRO = "price_server_owned_pro"
PRICE_TEAM = "price_server_owned_team"


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


def seed_tenant(plan="free", status="active"):
    with TestingSessionLocal() as db:
        tenant = Tenant(name="Checkout Tenant", plan=plan, status=status)
        workspace = Workspace(name="Default", slug="default", tenant=tenant)
        plaintext = "mbs_checkout_test_key_abcdefghijklmnopqrstuvwxyz"
        workspace.api_keys.append(
            ApiKey(
                name="Checkout key",
                key_prefix=plaintext[:12],
                key_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
                is_active=True,
            )
        )
        db.add(tenant)
        db.commit()
        return tenant.id, plaintext


def configure_checkout_env(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_checkout_placeholder")
    monkeypatch.setenv("STRIPE_PRICE_PRO", PRICE_PRO)
    monkeypatch.setenv("STRIPE_PRICE_TEAM", PRICE_TEAM)
    monkeypatch.setenv("BILLING_SUCCESS_URL", SUCCESS_URL)
    monkeypatch.setenv("BILLING_CANCEL_URL", CANCEL_URL)


def install_stripe_create(monkeypatch, session=None, error=None):
    captured = {}

    def fake_create(**kwargs):
        captured.clear()
        captured.update(kwargs)
        if error is not None:
            raise error
        return session or SimpleNamespace(
            id="cs_test_123",
            url="https://checkout.stripe.com/c/pay/cs_test_123",
        )

    monkeypatch.setattr(billing_router.stripe.checkout.Session, "create", fake_create)
    return captured


def post_checkout(key=None, payload=None):
    headers = {"X-MemoryBridge-Key": key} if key else {}
    return client.post("/v1/billing/checkout", json=payload or {"plan": "pro"}, headers=headers)


def test_checkout_without_api_key_fails(monkeypatch):
    reset_database()
    configure_checkout_env(monkeypatch)
    install_stripe_create(monkeypatch)
    response = post_checkout()
    assert response.status_code == 401
    assert response.json()["detail"] == "Missing service API key"


def test_legacy_key_cannot_create_checkout(monkeypatch):
    reset_database()
    configure_checkout_env(monkeypatch)
    captured = install_stripe_create(monkeypatch)
    response = post_checkout(LEGACY_KEY)
    assert response.status_code == 403
    assert response.json()["detail"] == "Workspace API key required"
    assert captured == {}


def test_workspace_key_creates_subscription_checkout_for_pro(monkeypatch):
    reset_database()
    tenant_id, key = seed_tenant()
    configure_checkout_env(monkeypatch)
    captured = install_stripe_create(monkeypatch)
    response = post_checkout(key, {"plan": "pro", "price_id": "price_attacker", "success_url": "https://evil.example/hijack"})
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"checkout_url", "session_id"}
    assert body["checkout_url"] == "https://checkout.stripe.com/c/pay/cs_test_123"
    assert body["session_id"] == "cs_test_123"
    assert captured["mode"] == "subscription"
    assert captured["line_items"] == [{"price": PRICE_PRO, "quantity": 1}]
    assert captured["success_url"] == SUCCESS_URL
    assert captured["cancel_url"] == CANCEL_URL
    assert captured["metadata"]["tenant_id"] == tenant_id
    assert captured["metadata"]["plan"] == "pro"
    assert captured["subscription_data"]["metadata"]["tenant_id"] == tenant_id
    assert captured["subscription_data"]["metadata"]["plan"] == "pro"
    assert "price_attacker" not in str(captured)
    assert "evil.example" not in str(captured)
    with TestingSessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        assert tenant.plan == "free"
        assert tenant.subscription_status is None
        assert tenant.stripe_customer_id is None
        assert tenant.stripe_subscription_id is None
        assert db.query(BillingEvent).count() == 0


def test_plan_team_uses_only_server_owned_team_price(monkeypatch):
    reset_database()
    tenant_id, key = seed_tenant()
    configure_checkout_env(monkeypatch)
    captured = install_stripe_create(monkeypatch)
    response = post_checkout(key, {"plan": "team"})
    assert response.status_code == 200
    assert captured["line_items"] == [{"price": PRICE_TEAM, "quantity": 1}]
    assert PRICE_PRO not in str(captured["line_items"])
    assert captured["metadata"]["plan"] == "team"
    assert captured["subscription_data"]["metadata"]["plan"] == "team"
    assert captured["metadata"]["tenant_id"] == tenant_id
    assert captured["success_url"] == SUCCESS_URL
    assert captured["cancel_url"] == CANCEL_URL
    with TestingSessionLocal() as db:
        assert db.get(Tenant, tenant_id).plan == "free"
        assert db.query(BillingEvent).count() == 0


def test_arbitrary_price_id_as_plan_is_rejected(monkeypatch):
    reset_database()
    _, key = seed_tenant()
    configure_checkout_env(monkeypatch)
    captured = install_stripe_create(monkeypatch)
    response = post_checkout(key, {"plan": "price_attacker_injected"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported paid plan"
    assert captured == {}


def test_stripe_provider_error_returns_safe_502(monkeypatch):
    reset_database()
    tenant_id, key = seed_tenant()
    configure_checkout_env(monkeypatch)
    install_stripe_create(monkeypatch, error=stripe.StripeError("raw provider failure containing sk_test_leak"))
    response = post_checkout(key)
    assert response.status_code == 502
    assert response.json() == {"detail": "Billing provider error"}
    assert "raw provider" not in response.text
    assert "sk_test_leak" not in response.text
    with TestingSessionLocal() as db:
        assert db.get(Tenant, tenant_id).plan == "free"
        assert db.query(BillingEvent).count() == 0


def test_stripe_response_without_checkout_url_fails_safely(monkeypatch):
    reset_database()
    tenant_id, key = seed_tenant()
    configure_checkout_env(monkeypatch)
    install_stripe_create(monkeypatch, session=SimpleNamespace(id="cs_missing_url", url=None))
    response = post_checkout(key)
    assert response.status_code == 502
    assert response.json() == {"detail": "Billing provider did not return a checkout URL"}
    with TestingSessionLocal() as db:
        assert db.get(Tenant, tenant_id).plan == "free"
        assert db.query(BillingEvent).count() == 0


def test_invalid_plan_fails_safely(monkeypatch):
    reset_database()
    _, key = seed_tenant()
    configure_checkout_env(monkeypatch)
    captured = install_stripe_create(monkeypatch)
    response = post_checkout(key, {"plan": "enterprise"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported paid plan"
    assert captured == {}


def test_inactive_tenant_cannot_create_checkout(monkeypatch):
    reset_database()
    _, key = seed_tenant(status="suspended")
    configure_checkout_env(monkeypatch)
    captured = install_stripe_create(monkeypatch)
    response = post_checkout(key)
    assert response.status_code in {401, 403}
    assert captured == {}
