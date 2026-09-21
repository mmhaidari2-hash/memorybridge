"""Stripe webhook idempotency and subscription state locking."""

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

from app.billing import ensure_plans, ensure_subscription
from app.config import clear_settings_cache
from app.database import Base, get_db, set_session_factory
from app.models import Plan, StripeWebhookEvent, Tenant, TenantSubscription
from app.rate_limit import rate_limiter
from app import stripe_billing
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
set_session_factory(TestingSessionLocal)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)


def reset_database():
    set_session_factory(TestingSessionLocal)
    app.dependency_overrides[get_db] = override_get_db
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    rate_limiter.reset()
    with TestingSessionLocal() as db:
        ensure_plans(db)


def _seed_tenant() -> str:
    created = client.post(
        "/v1/admin/tenants",
        json={"name": "Stripe Co", "slug": "stripe-co"},
        headers=ADMIN_HEADERS,
    )
    assert created.status_code == 201
    return created.json()["id"]


def test_checkout_completed_activates_plan_idempotently():
    reset_database()
    tenant_id = _seed_tenant()

    event = {
        "id": "evt_test_checkout_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_1",
                "customer": "cus_test_1",
                "subscription": "sub_test_1",
                "client_reference_id": tenant_id,
                "metadata": {"tenant_id": tenant_id, "plan_code": "starter"},
            }
        },
    }

    with TestingSessionLocal() as db:
        first = stripe_billing.process_stripe_event(db, event)
        assert first["duplicate"] is False
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
        assert plan.code == "starter"
        assert sub.status == "active"
        assert sub.stripe_subscription_id == "sub_test_1"

    with TestingSessionLocal() as db:
        second = stripe_billing.process_stripe_event(db, event)
        assert second["duplicate"] is True
        assert db.query(StripeWebhookEvent).filter(StripeWebhookEvent.id == "evt_test_checkout_1").count() == 1


def test_subscription_deleted_and_payment_failed_states():
    reset_database()
    tenant_id = _seed_tenant()

    with TestingSessionLocal() as db:
        stripe_billing.process_stripe_event(
            db,
            {
                "id": "evt_activate",
                "type": "checkout.session.completed",
                "data": {
                    "object": {
                        "id": "cs_2",
                        "customer": "cus_2",
                        "subscription": "sub_2",
                        "metadata": {"tenant_id": tenant_id, "plan_code": "growth"},
                    }
                },
            },
        )

    with TestingSessionLocal() as db:
        stripe_billing.process_stripe_event(
            db,
            {
                "id": "evt_fail",
                "type": "invoice.payment_failed",
                "data": {
                    "object": {
                        "id": "in_fail",
                        "customer": "cus_2",
                        "subscription": "sub_2",
                        "metadata": {"tenant_id": tenant_id},
                    }
                },
            },
        )
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        assert sub.status == "past_due"

    with TestingSessionLocal() as db:
        stripe_billing.process_stripe_event(
            db,
            {
                "id": "evt_del",
                "type": "customer.subscription.deleted",
                "data": {
                    "object": {
                        "id": "sub_2",
                        "customer": "cus_2",
                        "metadata": {"tenant_id": tenant_id},
                    }
                },
            },
        )
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
        assert plan.code == "free"
        assert sub.status == "canceled"


def test_webhook_rejects_missing_signature():
    reset_database()
    response = client.post("/v1/billing/webhook", content=b"{}")
    assert response.status_code == 400
