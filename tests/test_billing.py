import base64
import hashlib
import os

import stripe
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
    try: yield db
    finally: db.close()
app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def reset_database():
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine); Base.metadata.create_all(bind=engine)

def seed_tenant(plan="free"):
    with TestingSessionLocal() as db:
        tenant = Tenant(name="Billing Tenant", plan=plan, status="active")
        workspace = Workspace(name="Default", slug="default", tenant=tenant)
        plaintext = "mbs_billing_test_key_abcdefghijklmnopqrstuvwxyz"
        workspace.api_keys.append(ApiKey(name="Billing key", key_prefix=plaintext[:12], key_hash=hashlib.sha256(plaintext.encode()).hexdigest(), is_active=True))
        db.add(tenant); db.commit(); return tenant.id, plaintext

def post_event(monkeypatch, event, signature="sig_test"):
    seen = {}
    def fake_construct_event(payload, supplied_signature, secret):
        seen.update(signature=supplied_signature, secret=secret); return event
    monkeypatch.setattr(billing_router.stripe.Webhook, "construct_event", fake_construct_event)
    response = client.post("/v1/billing/webhook", content=b"{}", headers={"Stripe-Signature": signature, "Content-Type": "application/json"})
    assert seen == {"signature": signature, "secret": "whsec_test_secret"}; return response

def event(event_id, event_type, tenant_id, **fields):
    obj = {"metadata": {"tenant_id": tenant_id, "plan": fields.pop("plan", "pro")}, **fields}
    return {"id": event_id, "type": event_type, "data": {"object": obj}}

def test_billing_status_requires_workspace_key():
    reset_database()
    assert client.get("/v1/billing/status").status_code in {401, 403}

def test_billing_status_exposes_mode_without_secrets(monkeypatch):
    reset_database(); _, key = seed_tenant()
    monkeypatch.setenv("BILLING_MODE", "test")
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", "whsec_example")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro")
    monkeypatch.setenv("STRIPE_PRICE_TEAM", "price_team")
    monkeypatch.setenv("BILLING_SUCCESS_URL", "https://staging.example/app/dashboard.html?billing=success")
    monkeypatch.setenv("BILLING_CANCEL_URL", "https://staging.example/app/dashboard.html?billing=cancel")
    response = client.get("/v1/billing/status", headers={"X-MemoryBridge-Key": key})
    assert response.status_code == 200
    assert response.json() == {"mode": "test", "checkout_configured": True, "webhook_configured": True}
    assert "sk_test_example" not in response.text and "whsec_example" not in response.text

def test_checkout_completion_does_not_grant_paid_plan(monkeypatch):
    reset_database(); tenant_id, _ = seed_tenant()
    e = event("evt_checkout_1", "checkout.session.completed", tenant_id, client_reference_id=tenant_id, customer="cus_123", subscription="sub_123")
    assert post_event(monkeypatch, e).status_code == 200
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); assert t.plan=="free"; assert t.stripe_customer_id=="cus_123"; assert t.stripe_subscription_id=="sub_123"

def test_active_subscription_grants_pro_and_duplicate_is_idempotent(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant(); e=event("evt_sub_active_1","customer.subscription.updated",tenant_id,id="sub_123",customer="cus_123",status="active")
    assert post_event(monkeypatch,e).json()["duplicate"] is False; assert post_event(monkeypatch,e).json()["duplicate"] is True
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); assert t.plan=="pro"; assert t.subscription_status=="active"; assert db.query(BillingEvent).filter_by(provider_event_id="evt_sub_active_1").count()==1

def test_invoice_success_syncs_known_paid_subscription(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant(plan="pro")
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); t.stripe_subscription_id="sub_paid"; t.subscription_status="active"; db.commit()
    e={"id":"evt_invoice_ok","type":"invoice.payment_succeeded","data":{"object":{"subscription":"sub_paid","customer":"cus_paid"}}}
    assert post_event(monkeypatch,e).status_code==200
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); assert t.plan=="pro"; assert t.subscription_status=="active"

def test_invoice_success_cannot_create_paid_entitlement(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant()
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); t.stripe_subscription_id="sub_free"; db.commit()
    e={"id":"evt_invoice_free","type":"invoice.payment_succeeded","data":{"object":{"subscription":"sub_free"}}}
    response=post_event(monkeypatch,e); assert response.status_code==400
    with TestingSessionLocal() as db:
        assert db.get(Tenant,tenant_id).plan=="free"; assert db.query(BillingEvent).filter_by(provider_event_id="evt_invoice_free").count()==0

def test_payment_failure_never_grants_access(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant()
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); t.stripe_subscription_id="sub_failed"; db.commit()
    e={"id":"evt_invoice_failed","type":"invoice.payment_failed","data":{"object":{"subscription":"sub_failed"}}}
    assert post_event(monkeypatch,e).status_code==200
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); assert t.plan=="free"; assert t.subscription_status=="past_due"

def test_canceled_subscription_downgrades_to_free(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant(plan="pro"); e=event("evt_sub_deleted_1","customer.subscription.deleted",tenant_id,id="sub_123",customer="cus_123",status="canceled")
    assert post_event(monkeypatch,e).status_code==200
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); assert t.plan=="free"; assert t.subscription_status=="canceled"

def test_invalid_plan_rolls_back_event_and_entitlement(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant(); e=event("evt_bad_plan_1","customer.subscription.updated",tenant_id,plan="enterprise-hack",id="sub_bad",status="active")
    assert post_event(monkeypatch,e).status_code==400
    with TestingSessionLocal() as db:
        assert db.get(Tenant,tenant_id).plan=="free"; assert db.query(BillingEvent).filter_by(provider_event_id="evt_bad_plan_1").count()==0

def test_missing_signature_is_rejected_without_database_write():
    reset_database(); tenant_id,_=seed_tenant(); response=client.post("/v1/billing/webhook",content=b"{}")
    assert response.status_code==400
    with TestingSessionLocal() as db:
        assert db.get(Tenant,tenant_id).plan=="free"; assert db.query(BillingEvent).count()==0

def test_invalid_signature_is_rejected_without_database_write(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant()
    def reject(*args,**kwargs): raise stripe.SignatureVerificationError("bad signature","sig")
    monkeypatch.setattr(billing_router.stripe.Webhook,"construct_event",reject)
    response=client.post("/v1/billing/webhook",content=b"{}",headers={"Stripe-Signature":"invalid"}); assert response.status_code==400
    with TestingSessionLocal() as db:
        assert db.get(Tenant,tenant_id).plan=="free"; assert db.query(BillingEvent).count()==0


SUCCESS_URL = "https://staging.example/app/dashboard.html?billing=success"
CANCEL_URL = "https://staging.example/app/dashboard.html?billing=cancel"


def configure_checkout(monkeypatch):
    monkeypatch.setenv("STRIPE_SECRET_KEY", "sk_test_example")
    monkeypatch.setenv("STRIPE_PRICE_PRO", "price_pro_server")
    monkeypatch.setenv("STRIPE_PRICE_TEAM", "price_team_server")
    monkeypatch.setenv("BILLING_SUCCESS_URL", SUCCESS_URL)
    monkeypatch.setenv("BILLING_CANCEL_URL", CANCEL_URL)


class FakeCheckoutSession:
    def __init__(self, url="https://checkout.stripe.com/c/pay/cs_test_1", session_id="cs_test_1"):
        self.url = url
        self.id = session_id


def capture_checkout_create(monkeypatch, session=None, error=None):
    seen = {}

    def fake_create(**kwargs):
        seen.update(kwargs)
        if error is not None:
            raise error
        return session if session is not None else FakeCheckoutSession()

    monkeypatch.setattr(billing_router.stripe.checkout.Session, "create", fake_create)
    return seen


def test_checkout_requires_database_workspace_key(monkeypatch):
    reset_database()
    configure_checkout(monkeypatch)
    capture_checkout_create(monkeypatch)
    assert client.post("/v1/billing/checkout", json={"plan": "pro"}).status_code in {401, 403}
    monkeypatch.setenv("SERVICE_API_KEYS", "mbs_legacy_checkout_key")
    from app.service_auth import get_legacy_service_key_hashes
    get_legacy_service_key_hashes.cache_clear()
    response = client.post(
        "/v1/billing/checkout",
        json={"plan": "pro"},
        headers={"X-MemoryBridge-Key": "mbs_legacy_checkout_key"},
    )
    assert response.status_code == 403


def test_checkout_pro_uses_server_price_subscription_metadata_and_redirects(monkeypatch):
    reset_database()
    tenant_id, key = seed_tenant()
    configure_checkout(monkeypatch)
    seen = capture_checkout_create(monkeypatch)
    response = client.post(
        "/v1/billing/checkout",
        json={"plan": "pro", "price_id": "price_attacker_supplied", "price": "price_attacker_supplied"},
        headers={"X-MemoryBridge-Key": key},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["session_id"] == "cs_test_1"
    assert body["checkout_url"].startswith("https://checkout.stripe.com/")
    assert seen["mode"] == "subscription"
    assert seen["line_items"] == [{"price": "price_pro_server", "quantity": 1}]
    assert seen["success_url"] == SUCCESS_URL
    assert seen["cancel_url"] == CANCEL_URL
    assert seen["client_reference_id"] == tenant_id
    assert seen["metadata"] == {"tenant_id": tenant_id, "plan": "pro"}
    assert seen["subscription_data"]["metadata"] == {"tenant_id": tenant_id, "plan": "pro"}
    with TestingSessionLocal() as db:
        tenant = db.get(Tenant, tenant_id)
        assert tenant.plan == "free"
        assert tenant.subscription_status is None
        assert db.query(BillingEvent).count() == 0


def test_checkout_team_uses_server_owned_team_price(monkeypatch):
    reset_database()
    tenant_id, key = seed_tenant()
    configure_checkout(monkeypatch)
    seen = capture_checkout_create(monkeypatch)
    response = client.post(
        "/v1/billing/checkout",
        json={"plan": "team"},
        headers={"X-MemoryBridge-Key": key},
    )
    assert response.status_code == 200
    assert seen["mode"] == "subscription"
    assert seen["line_items"] == [{"price": "price_team_server", "quantity": 1}]
    assert seen["metadata"] == {"tenant_id": tenant_id, "plan": "team"}
    with TestingSessionLocal() as db:
        assert db.get(Tenant, tenant_id).plan == "free"


def test_checkout_rejects_unsupported_plan_without_calling_stripe(monkeypatch):
    reset_database()
    _, key = seed_tenant()
    configure_checkout(monkeypatch)
    seen = capture_checkout_create(monkeypatch)
    response = client.post(
        "/v1/billing/checkout",
        json={"plan": "price_attacker_supplied"},
        headers={"X-MemoryBridge-Key": key},
    )
    assert response.status_code == 400
    assert seen == {}


def test_checkout_provider_error_returns_safe_502(monkeypatch):
    reset_database()
    tenant_id, key = seed_tenant()
    configure_checkout(monkeypatch)
    capture_checkout_create(monkeypatch, error=stripe.StripeError("card_decline secret=sk_test_leaked"))
    response = client.post(
        "/v1/billing/checkout",
        json={"plan": "pro"},
        headers={"X-MemoryBridge-Key": key},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Billing provider error"
    assert "sk_test_leaked" not in response.text
    assert "card_decline" not in response.text
    with TestingSessionLocal() as db:
        assert db.get(Tenant, tenant_id).plan == "free"


def test_checkout_missing_url_fails_closed_without_plan_change(monkeypatch):
    reset_database()
    tenant_id, key = seed_tenant()
    configure_checkout(monkeypatch)
    capture_checkout_create(monkeypatch, session=FakeCheckoutSession(url="", session_id="cs_missing_url"))
    response = client.post(
        "/v1/billing/checkout",
        json={"plan": "pro"},
        headers={"X-MemoryBridge-Key": key},
    )
    assert response.status_code == 502
    assert response.json()["detail"] == "Billing provider did not return a checkout URL"
    with TestingSessionLocal() as db:
        assert db.get(Tenant, tenant_id).plan == "free"
        assert db.query(BillingEvent).count() == 0
