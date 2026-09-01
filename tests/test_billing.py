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

def test_invoice_success_before_subscription_is_acknowledged_without_entitlement(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant()
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); t.stripe_subscription_id="sub_free"; db.commit()
    e={"id":"evt_invoice_free","type":"invoice.payment_succeeded","data":{"object":{"subscription":"sub_free"}}}
    response=post_event(monkeypatch,e); assert response.status_code==200
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); assert t.plan=="free"; assert t.subscription_status is None; assert db.query(BillingEvent).filter_by(provider_event_id="evt_invoice_free").count()==1

def test_invoice_then_subscription_event_grants_entitlement_only_on_subscription(monkeypatch):
    reset_database(); tenant_id,_=seed_tenant()
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); t.stripe_subscription_id="sub_ordered"; db.commit()
    invoice={"id":"evt_invoice_first","type":"invoice.payment_succeeded","data":{"object":{"subscription":"sub_ordered"}}}
    assert post_event(monkeypatch,invoice).status_code==200
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); assert t.plan=="free"; assert t.subscription_status is None
    subscription=event("evt_sub_second","customer.subscription.created",tenant_id,id="sub_ordered",customer="cus_ordered",status="active")
    assert post_event(monkeypatch,subscription).status_code==200
    with TestingSessionLocal() as db:
        t=db.get(Tenant,tenant_id); assert t.plan=="pro"; assert t.subscription_status=="active"; assert db.query(BillingEvent).filter(BillingEvent.provider_event_id.in_(["evt_invoice_first","evt_sub_second"])).count()==2

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
