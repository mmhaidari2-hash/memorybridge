import os

import stripe
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.billing import configure_stripe, price_id_for_plan, webhook_secret
from app.database import get_db
from app.models import BillingEvent, Tenant
from app.service_auth import ServiceAuthContext, verify_service_api_key

router = APIRouter(tags=["Billing"])


class CheckoutRequest(BaseModel):
    plan: str


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


@router.post("/billing/checkout", response_model=CheckoutResponse)
def create_checkout(payload: CheckoutRequest, db: Session = Depends(get_db), auth: ServiceAuthContext = Depends(verify_service_api_key)):
    if auth.tenant_id is None or auth.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace API key required")
    tenant = db.get(Tenant, auth.tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=403, detail="Tenant is not active")
    configure_stripe()
    price_id = price_id_for_plan(payload.plan)
    success_url = os.getenv("BILLING_SUCCESS_URL", "").strip()
    cancel_url = os.getenv("BILLING_CANCEL_URL", "").strip()
    if not success_url or not cancel_url:
        raise HTTPException(status_code=503, detail="Billing redirect URLs are not configured")
    try:
        session = stripe.checkout.Session.create(mode="subscription", line_items=[{"price": price_id, "quantity": 1}], success_url=success_url, cancel_url=cancel_url, client_reference_id=tenant.id, metadata={"tenant_id": tenant.id, "plan": payload.plan}, subscription_data={"metadata": {"tenant_id": tenant.id, "plan": payload.plan}})
    except stripe.StripeError as exc:
        raise HTTPException(status_code=502, detail="Billing provider error") from exc
    if not session.url:
        raise HTTPException(status_code=502, detail="Billing provider did not return a checkout URL")
    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


def _metadata_value(obj, key: str):
    return (obj.get("metadata") or {}).get(key)


def _tenant_from_event(db: Session, event_type: str, obj) -> Tenant | None:
    tenant_id = _metadata_value(obj, "tenant_id")
    if not tenant_id and event_type == "checkout.session.completed":
        tenant_id = obj.get("client_reference_id")
    if tenant_id:
        return db.get(Tenant, tenant_id)
    # Invoice events do not reliably copy subscription metadata. Resolve only
    # against Stripe identifiers already established by trusted prior events.
    subscription_id = obj.get("subscription")
    if subscription_id:
        tenant = db.query(Tenant).filter(Tenant.stripe_subscription_id == str(subscription_id)).one_or_none()
        if tenant:
            return tenant
    customer_id = obj.get("customer")
    if customer_id:
        return db.query(Tenant).filter(Tenant.stripe_customer_id == str(customer_id)).one_or_none()
    return None


@router.post("/billing/webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature"), db: Session = Depends(get_db)):
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, webhook_secret())
    except (ValueError, stripe.SignatureVerificationError) as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook") from exc

    event_id = event.get("id")
    event_type = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Malformed Stripe webhook")
    supported = {"checkout.session.completed", "invoice.payment_succeeded", "invoice.payment_failed", "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}
    if event_type not in supported:
        return {"received": True, "handled": False}
    tenant = _tenant_from_event(db, event_type, obj)
    if tenant is None:
        raise HTTPException(status_code=400, detail="Webhook tenant not found")

    processed = BillingEvent(tenant_id=tenant.id, provider_event_id=event_id, event_type=event_type)
    db.add(processed)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {"received": True, "handled": True, "duplicate": True}

    try:
        if event_type == "checkout.session.completed":
            if obj.get("customer"):
                tenant.stripe_customer_id = str(obj.get("customer"))
            if obj.get("subscription"):
                tenant.stripe_subscription_id = str(obj.get("subscription"))
            # Checkout completion alone never grants a paid plan.
        elif event_type in {"customer.subscription.created", "customer.subscription.updated"}:
            plan = _metadata_value(obj, "plan")
            status = obj.get("status")
            if plan not in {"pro", "team"}:
                raise ValueError("Webhook plan is invalid")
            tenant.stripe_subscription_id = str(obj.get("id")) if obj.get("id") else tenant.stripe_subscription_id
            if obj.get("customer"):
                tenant.stripe_customer_id = str(obj.get("customer"))
            tenant.subscription_status = status
            tenant.plan = plan if status in {"active", "trialing"} else "free"
        elif event_type == "invoice.payment_succeeded":
            # A successful invoice confirms billing health but cannot invent or
            # upgrade a plan. Entitlement remains sourced from subscription events.
            if tenant.plan not in {"pro", "team"}:
                raise ValueError("Successful invoice has no established paid entitlement")
            tenant.subscription_status = "active"
        elif event_type == "invoice.payment_failed":
            # Record payment health without granting access. Stripe subscription
            # lifecycle events remain authoritative for entitlement removal.
            tenant.subscription_status = "past_due"
        elif event_type == "customer.subscription.deleted":
            tenant.subscription_status = obj.get("status") or "canceled"
            tenant.plan = "free"
            if obj.get("id"):
                tenant.stripe_subscription_id = str(obj.get("id"))
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
    return {"received": True, "handled": True, "duplicate": False}
