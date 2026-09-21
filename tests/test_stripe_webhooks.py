"""Stripe webhook async acceptance, idempotency, and out-of-order protection."""

import os
from unittest.mock import patch

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

from app.billing import ensure_plans
from app.config import clear_settings_cache
from app.database import Base, get_db, set_session_factory
from app.models import Plan, StripeWebhookEvent, TenantSubscription
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
        "created": 1_700_000_100,
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

    first = stripe_billing.process_stripe_event(event)
    assert first["duplicate"] is False
    with TestingSessionLocal() as db:
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
        assert plan.code == "starter"
        assert sub.status == "active"
        assert sub.stripe_subscription_id == "sub_test_1"
        assert sub.last_stripe_event_ts == 1_700_000_100

    second = stripe_billing.process_stripe_event(event)
    assert second["duplicate"] is True
    with TestingSessionLocal() as db:
        assert db.query(StripeWebhookEvent).filter(StripeWebhookEvent.id == "evt_test_checkout_1").count() == 1


def test_subscription_deleted_and_payment_failed_states():
    reset_database()
    tenant_id = _seed_tenant()

    stripe_billing.process_stripe_event(
        {
            "id": "evt_activate",
            "type": "checkout.session.completed",
            "created": 1_700_000_200,
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

    stripe_billing.process_stripe_event(
        {
            "id": "evt_fail",
            "type": "invoice.payment_failed",
            "created": 1_700_000_300,
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
    with TestingSessionLocal() as db:
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        assert sub.status == "past_due"
        assert sub.last_stripe_event_ts == 1_700_000_300

    stripe_billing.process_stripe_event(
        {
            "id": "evt_del",
            "type": "customer.subscription.deleted",
            "created": 1_700_000_400,
            "data": {
                "object": {
                    "id": "sub_2",
                    "customer": "cus_2",
                    "metadata": {"tenant_id": tenant_id},
                }
            },
        },
    )
    with TestingSessionLocal() as db:
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
        assert plan.code == "free"
        assert sub.status == "canceled"
        assert sub.last_stripe_event_ts == 1_700_000_400


def test_stale_out_of_order_event_discarded():
    reset_database()
    tenant_id = _seed_tenant()

    stripe_billing.process_stripe_event(
        {
            "id": "evt_newer",
            "type": "customer.subscription.updated",
            "created": 1_700_000_500,
            "data": {
                "object": {
                    "id": "sub_oo",
                    "customer": "cus_oo",
                    "status": "active",
                    "metadata": {"tenant_id": tenant_id, "plan_code": "starter"},
                }
            },
        },
    )
    with TestingSessionLocal() as db:
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
        assert plan.code == "starter"
        assert sub.status == "active"
        assert sub.last_stripe_event_ts == 1_700_000_500

    # Older event arrives late — must not clobber newer state.
    stripe_billing.process_stripe_event(
        {
            "id": "evt_stale",
            "type": "invoice.payment_failed",
            "created": 1_700_000_100,
            "data": {
                "object": {
                    "id": "in_stale",
                    "customer": "cus_oo",
                    "subscription": "sub_oo",
                    "metadata": {"tenant_id": tenant_id},
                }
            },
        },
    )
    with TestingSessionLocal() as db:
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
        assert plan.code == "starter"
        assert sub.status == "active"
        assert sub.last_stripe_event_ts == 1_700_000_500


def test_webhook_rejects_missing_signature():
    reset_database()
    response = client.post("/v1/billing/webhook", content=b"{}")
    assert response.status_code == 400


def test_webhook_accepts_async_and_returns_received():
    reset_database()
    tenant_id = _seed_tenant()
    event = {
        "id": "evt_async_1",
        "type": "checkout.session.completed",
        "created": 1_700_000_600,
        "data": {
            "object": {
                "id": "cs_async",
                "customer": "cus_async",
                "subscription": "sub_async",
                "metadata": {"tenant_id": tenant_id, "plan_code": "starter"},
            }
        },
    }

    with patch.object(stripe_billing, "read_webhook_payload", return_value=(b"{}", "sig")):
        with patch.object(stripe_billing, "construct_webhook_event", return_value=event):
            response = client.post(
                "/v1/billing/webhook",
                content=b"{}",
                headers={"Stripe-Signature": "sig"},
            )

    assert response.status_code == 200
    assert response.json() == {"status": "received"}
    # TestClient drains BackgroundTasks before returning.
    with TestingSessionLocal() as db:
        sub = db.query(TenantSubscription).filter(TenantSubscription.tenant_id == tenant_id).one()
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
        assert plan.code == "starter"
        assert sub.last_stripe_event_ts == 1_700_000_600
