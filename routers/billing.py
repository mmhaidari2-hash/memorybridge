import logging
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
logger = logging.getLogger("memorybridge.billing")


class CheckoutRequest(BaseModel):
    plan: str


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


@router.get("/billing/status")
def billing_status(auth: ServiceAuthContext = Depends(verify_service_api_key)):
    # The deployment smoke probe is part of the customer control plane, not a
    # public configuration fingerprint endpoint. Require a DB-backed workspace
    # key just like checkout itself does.
    if auth.tenant_id is None or auth.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace API key required")
    mode = os.getenv("BILLING_MODE", "").strip().lower() or "unconfigured"
    checkout_configured = all(
        os.getenv(name, "").strip()
        for name in (
            "STRIPE_SECRET_KEY",
            "STRIPE_PRICE_PRO",
            "STRIPE_PRICE_TEAM",
            "BILLING_SUCCESS_URL",
            "BILLING_CANCEL_URL",
        )
    )
    webhook_configured = bool(os.getenv("STRIPE_WEBHOOK_SECRET", "").strip())
    return {"mode": mode, "checkout_configured": checkout_configured, "webhook_configured": webhook_configured}


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
        logger.warning("checkout_provider_error tenant_id=%s plan=%s", tenant.id, payload.plan)
        raise HTTPException(status_code=502, detail="Billing provider error") from exc
    if not session.url:
        logger.warning("checkout_missing_url tenant_id=%s plan=%s", tenant.id, payload.plan)
        raise HTTPException(status_code=502, detail="Billing provider did not return a checkout URL")
    logger.info("checkout_created tenant_id=%s plan=%s", tenant.id, payload.plan)
    return CheckoutResponse(checkout_url=session.url, session_id=session.id)


def _metadata_value(obj, key: str):
    return (obj.get("metadata") or {}).get(key)


def _tenant_from_event(db: Session, event_type: str, obj) -> Tenant | None:
    tenant_id = _metadata_value(obj, "tenant_id")
    if not tenant_id and event_type == "checkout.session.completed":
        tenant_id = obj.get("client_reference_id")
    if tenant_id:
        return db.get(Tenant, tenant_id)
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
        logger.warning("webhook_rejected reason=missing_signature")
        raise HTTPException(status_code=400, detail="Missing Stripe signature")
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, stripe_signature, webhook_secret())
    except (ValueError, stripe.SignatureVerificationError) as exc:
        logger.warning("webhook_rejected reason=invalid_signature")
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook") from exc

    event_id = event.get("id")
    event_type = event.get("type")
    obj = (event.get("data") or {}).get("object") or {}
    if not event_id or not event_type:
        logger.warning("webhook_rejected reason=malformed_event")
        raise HTTPException(status_code=400, detail="Malformed Stripe webhook")
    supported = {"checkout.session.completed", "invoice.payment_succeeded", "invoice.payment_failed", "customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"}
    if event_type not in supported:
        logger.info("webhook_ignored event_id=%s event_type=%s", event_id, event_type)
        return {"received": True, "handled": False}
    tenant = _tenant_from_event(db, event_type, obj)
    if tenant is None:
        logger.warning("webhook_rejected event_id=%s event_type=%s reason=tenant_not_found", event_id, event_type)
        raise HTTPException(status_code=400, detail="Webhook tenant not found")

    processed = BillingEvent(tenant_id=tenant.id, provider_event_id=event_id, event_type=event_type)
    db.add(processed)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info("webhook_duplicate tenant_id=%s event_id=%s event_type=%s", tenant.id, event_id, event_type)
        return {"received": True, "handled": True, "duplicate": True}

    try:
        if event_type == "checkout.session.completed":
            if obj.get("customer"):
                tenant.stripe_customer_id = str(obj.get("customer"))
            if obj.get("subscription"):
                tenant.stripe_subscription_id = str(obj.get("subscription"))
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
            # Stripe does not guarantee webhook delivery order. A successful
            # invoice may arrive before the subscription lifecycle event that
            # establishes the paid plan. Record and acknowledge the invoice,
            # but never let an invoice create paid entitlement by itself.
            if tenant.plan in {"pro", "team"}:
                tenant.subscription_status = "active"
            else:
                logger.info(
                    "invoice_payment_recorded_pending_entitlement tenant_id=%s event_id=%s",
                    tenant.id,
                    event_id,
                )
        elif event_type == "invoice.payment_failed":
            tenant.subscription_status = "past_due"
        elif event_type == "customer.subscription.deleted":
            tenant.subscription_status = obj.get("status") or "canceled"
            tenant.plan = "free"
            if obj.get("id"):
                tenant.stripe_subscription_id = str(obj.get("id"))
        db.commit()
    except ValueError as exc:
        db.rollback()
        logger.warning("webhook_rolled_back tenant_id=%s event_id=%s event_type=%s reason=validation", tenant.id, event_id, event_type)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        logger.exception("webhook_failed tenant_id=%s event_id=%s event_type=%s", tenant.id, event_id, event_type)
        raise
    logger.info("webhook_applied tenant_id=%s event_id=%s event_type=%s plan=%s subscription_status=%s", tenant.id, event_id, event_type, tenant.plan, tenant.subscription_status)
    return {"received": True, "handled": True, "duplicate": False}
