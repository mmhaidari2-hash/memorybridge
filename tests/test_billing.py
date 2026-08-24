import base64
import hashlib
import os

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))
os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test_secret"

from app.database import Base, get_db
from app.models import ApiKey, BillingEvent, Tenant, Workspace
from main import app
import routers.billing as billing_router

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


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


def seed_tenant(plan="free"):
    with TestingSessionLocal() as db:
        tenant = Tenant(name="Billing Tenant", plan=plan, status="active")
        workspace = Workspace(name="Default", slug="default", tenant=tenant)
        plaintext = "mbs_billing_test_key_abcdefghijklmnopqrstuvwxyz"
        workspace.api_keys.append(
            ApiKey(
                name="Billing key",
                key_prefix=plaintext[:12],
                key_hash=hashlib.sha256(plaintext.encode()).hexdigest(),
                is_active=True,
            )
        )
        db.add(tenant)
        db.commit()
        return tenant.id, plaintext


def post_event(monkeypatch, event, signature="sig_test"):
    seen = {}

    def fake_construct_event(payload, supplied_signature, secret):
        seen["signature"] = supplied_signature
        seen["secret"] = secret
        return event

    monkeypatch.setattr(billing_router.stripe.Webhook, "construct_event", fake_construct_event)
    response = client.post(
        "/v1/billing/webhook",
        content=b"{}",
        headers={"Stripe-Signature": signature, "Content-Type": "application/json"},
    )
    assert seen == {"signature": signature, "secret": "whsec_test_secret"}
    return response


def test_checkout_completion_does_not_grant_paid_plan(monkeypatch):
    reset_database()
    tenant_id, _ = seed_tenant()
    event = {
        "id": "evt_checkout_1",
        "type": "checkout.session.completed",
        "data": {"object": {
            "client_reference_id": tenant_id,
            "metadata": {"tenant_id": tenant_id, "plan": "pro"},
            "customer": "cus_123",
            "subscription": "sub_123",
        }},
    }
    response = post_event(monkeypatch, event)
    assert response.status_code == 200
    with TestingSessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        assert tenant.plan == "free"
        assert tenant.stripe_customer_id == "cus_123"
        assert tenant.stripe_subscription_id == "sub_123"


def test_active_subscription_grants_pro_and_duplicate_is_idempotent(monkeypatch):
    reset_database()
    tenant_id, _ = seed_tenant()
    event = {
        "id": "evt_sub_active_1",
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_123",
            "customer": "cus_123",
            "status": "active",
            "metadata": {"tenant_id": tenant_id, "plan": "pro"},
        }},
    }
    first = post_event(monkeypatch, event)
    assert first.status_code == 200
    assert first.json()["duplicate"] is False
    second = post_event(monkeypatch, event)
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    with TestingSessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        assert tenant.plan == "pro"
        assert tenant.subscription_status == "active"
        assert db.query(BillingEvent).filter(BillingEvent.provider_event_id == "evt_sub_active_1").count() == 1


def test_canceled_subscription_downgrades_to_free(monkeypatch):
    reset_database()
    tenant_id, _ = seed_tenant(plan="pro")
    event = {
        "id": "evt_sub_deleted_1",
        "type": "customer.subscription.deleted",
        "data": {"object": {
            "id": "sub_123",
            "customer": "cus_123",
            "status": "canceled",
            "metadata": {"tenant_id": tenant_id, "plan": "pro"},
        }},
    }
    response = post_event(monkeypatch, event)
    assert response.status_code == 200
    with TestingSessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        assert tenant.plan == "free"
        assert tenant.subscription_status == "canceled"


def test_invalid_plan_in_subscription_event_never_grants_access(monkeypatch):
    reset_database()
    tenant_id, _ = seed_tenant()
    event = {
        "id": "evt_bad_plan_1",
        "type": "customer.subscription.updated",
        "data": {"object": {
            "id": "sub_bad",
            "status": "active",
            "metadata": {"tenant_id": tenant_id, "plan": "enterprise-hack"},
        }},
    }
    response = post_event(monkeypatch, event)
    assert response.status_code == 400
    with TestingSessionLocal() as db:
        assert db.get(Tenant, tenant_id).plan == "free"


def test_missing_signature_is_rejected_without_entitlement_change():
    reset_database()
    tenant_id, _ = seed_tenant()
    response = client.post("/v1/billing/webhook", content=b"{}")
    assert response.status_code == 400
    assert response.json()["detail"] == "Missing Stripe signature"
    with TestingSessionLocal() as db:
        assert db.get(Tenant, tenant_id).plan == "free"
