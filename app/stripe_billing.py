"""Stripe checkout + webhook helpers. Optional until STRIPE_SECRET_KEY is set."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import stripe
from fastapi import HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.billing import ensure_plans, ensure_subscription, get_plan_by_code
from app.config import get_settings
from app.database import create_session
from app.models import Plan, StripeWebhookEvent, TenantSubscription, utc_now

logger = logging.getLogger("memorybridge.stripe")


def stripe_enabled() -> bool:
    return bool(get_settings().stripe_secret_key)


def _configure() -> None:
    settings = get_settings()
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "billing_not_configured",
                "message": "Stripe is not configured. Ask an admin to assign a paid plan, or set STRIPE_SECRET_KEY.",
            },
        )
    stripe.api_key = settings.stripe_secret_key


def create_checkout_session(
    *,
    tenant_id: str,
    tenant_slug: str,
    plan_code: str,
    stripe_price_id: str,
    customer_email: Optional[str] = None,
    existing_customer_id: Optional[str] = None,
) -> Dict[str, Any]:
    _configure()
    settings = get_settings()
    success = settings.billing_success_url or f"{settings.public_base_url}/billing/success"
    cancel = settings.billing_cancel_url or f"{settings.public_base_url}/billing/cancel"

    params: Dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": stripe_price_id, "quantity": 1}],
        "success_url": success + ("&" if "?" in success else "?") + "session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": cancel,
        "client_reference_id": tenant_id,
        "metadata": {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "plan_code": plan_code,
        },
        "subscription_data": {
            "metadata": {
                "tenant_id": tenant_id,
                "plan_code": plan_code,
            }
        },
    }
    if existing_customer_id:
        params["customer"] = existing_customer_id
    elif customer_email:
        params["customer_email"] = customer_email

    session = stripe.checkout.Session.create(**params)
    return {"checkout_url": session.url, "session_id": session.id}


def construct_webhook_event(request_body: bytes, signature: str):
    settings = get_settings()
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="STRIPE_WEBHOOK_SECRET is not configured")
    _configure()
    try:
        return stripe.Webhook.construct_event(
            payload=request_body,
            sig_header=signature,
            secret=settings.stripe_webhook_secret,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid Stripe webhook signature") from exc


async def read_webhook_payload(request: Request) -> tuple[bytes, str]:
    body = await request.body()
    signature = request.headers.get("Stripe-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header")
    return body, signature


def _ts_to_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).replace(tzinfo=None)
    except (TypeError, ValueError, OSError):
        return None


def _map_stripe_subscription_status(stripe_status: Optional[str]) -> str:
    mapping = {
        "active": "active",
        "trialing": "trialing",
        "past_due": "past_due",
        "unpaid": "past_due",
        "canceled": "canceled",
        "incomplete": "past_due",
        "incomplete_expired": "canceled",
        "paused": "past_due",
    }
    if not stripe_status:
        return "active"
    return mapping.get(stripe_status, "active")


def _plan_code_from_price_id(db: Session, price_id: Optional[str]) -> Optional[str]:
    if not price_id:
        return None
    ensure_plans(db)
    plan = db.query(Plan).filter(Plan.stripe_price_id == price_id).first()
    return plan.code if plan else None


def _price_id_from_subscription(subscription: Dict[str, Any]) -> Optional[str]:
    items = (subscription.get("items") or {}).get("data") or []
    if not items:
        return None
    price = items[0].get("price") or {}
    if isinstance(price, str):
        return price
    return price.get("id")


def _lock_subscription(
    db: Session,
    *,
    tenant_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    stripe_customer_id: Optional[str] = None,
) -> Optional[TenantSubscription]:
    query = db.query(TenantSubscription)
    if stripe_subscription_id:
        row = (
            query.filter(TenantSubscription.stripe_subscription_id == stripe_subscription_id)
            .with_for_update()
            .first()
        )
        if row:
            return row
    if tenant_id:
        row = (
            query.filter(TenantSubscription.tenant_id == tenant_id)
            .with_for_update()
            .first()
        )
        if row:
            return row
    if stripe_customer_id:
        return (
            query.filter(TenantSubscription.stripe_customer_id == stripe_customer_id)
            .with_for_update()
            .first()
        )
    return None


def apply_subscription_snapshot(
    db: Session,
    *,
    tenant_id: Optional[str],
    stripe_customer_id: Optional[str],
    stripe_subscription_id: Optional[str],
    plan_code: Optional[str],
    status: str,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
    event_created: Optional[int] = None,
) -> Optional[TenantSubscription]:
    """Idempotently sync TenantSubscription under a row-level lock.

    ``event_created`` is Stripe's ``event.created`` unix timestamp. Events at or
    before ``sub.last_stripe_event_ts`` are discarded (out-of-order / stale).
    """
    if not tenant_id and not stripe_subscription_id and not stripe_customer_id:
        return None

    if tenant_id:
        # Ensure a row exists before locking (first checkout race).
        ensure_subscription(db, tenant_id, plan_code=plan_code or "free", commit=False)

    sub = _lock_subscription(
        db,
        tenant_id=tenant_id,
        stripe_subscription_id=stripe_subscription_id,
        stripe_customer_id=stripe_customer_id,
    )
    if sub is None:
        logger.warning(
            "stripe_subscription_row_missing tenant_id=%s sub=%s customer=%s",
            tenant_id,
            stripe_subscription_id,
            stripe_customer_id,
        )
        return None

    if event_created is not None:
        created_ts = int(event_created)
        if created_ts <= int(sub.last_stripe_event_ts or 0):
            logger.info(
                "stale event discarded tenant_id=%s event_created=%s last_stripe_event_ts=%s",
                sub.tenant_id,
                created_ts,
                sub.last_stripe_event_ts,
            )
            return None

    if plan_code:
        plan = get_plan_by_code(db, plan_code)
        sub.plan_id = plan.id

    # Idempotent field writes — same values are no-ops for state corruption.
    if status:
        sub.status = status
    if stripe_customer_id:
        sub.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id:
        sub.stripe_subscription_id = stripe_subscription_id
    if period_start is not None:
        sub.current_period_start = period_start
    if period_end is not None:
        sub.current_period_end = period_end
    if event_created is not None:
        sub.last_stripe_event_ts = int(event_created)
    sub.updated_at = utc_now()
    db.add(sub)
    db.flush()
    return sub


def _claim_event(db: Session, event_id: str, event_type: str) -> bool:
    """Return True if this worker should process the event (first claim wins)."""
    if not event_id:
        return True
    existing = db.query(StripeWebhookEvent).filter(StripeWebhookEvent.id == event_id).first()
    if existing:
        return False
    try:
        with db.begin_nested():
            db.add(
                StripeWebhookEvent(
                    id=event_id,
                    event_type=event_type,
                    created_at=utc_now(),
                )
            )
            db.flush()
    except IntegrityError:
        return False
    return True


def handle_checkout_session_completed(
    db: Session,
    session: Dict[str, Any],
    *,
    event_created: Optional[int] = None,
) -> None:
    metadata = session.get("metadata") or {}
    tenant_id = metadata.get("tenant_id") or session.get("client_reference_id")
    plan_code = metadata.get("plan_code") or "starter"
    applied = apply_subscription_snapshot(
        db,
        tenant_id=tenant_id,
        stripe_customer_id=session.get("customer"),
        stripe_subscription_id=session.get("subscription"),
        plan_code=plan_code,
        status="active",
        event_created=event_created,
    )
    if tenant_id and applied is not None:
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type="stripe",
            actor_id=session.get("id"),
            action="billing.checkout_completed",
            outcome="success",
            resource_type="plan",
            resource_id=plan_code,
        )


def handle_subscription_updated(
    db: Session,
    subscription: Dict[str, Any],
    *,
    event_created: Optional[int] = None,
) -> None:
    metadata = subscription.get("metadata") or {}
    tenant_id = metadata.get("tenant_id")
    plan_code = metadata.get("plan_code") or _plan_code_from_price_id(
        db, _price_id_from_subscription(subscription)
    )
    status = _map_stripe_subscription_status(subscription.get("status"))
    applied = apply_subscription_snapshot(
        db,
        tenant_id=tenant_id,
        stripe_customer_id=subscription.get("customer"),
        stripe_subscription_id=subscription.get("id"),
        plan_code=plan_code,
        status=status,
        period_start=_ts_to_dt(subscription.get("current_period_start")),
        period_end=_ts_to_dt(subscription.get("current_period_end")),
        event_created=event_created,
    )
    if tenant_id and applied is not None:
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type="stripe",
            actor_id=subscription.get("id"),
            action="billing.subscription_updated",
            outcome="success",
            resource_type="subscription",
            resource_id=status,
        )


def handle_subscription_deleted(
    db: Session,
    subscription: Dict[str, Any],
    *,
    event_created: Optional[int] = None,
) -> None:
    metadata = subscription.get("metadata") or {}
    tenant_id = metadata.get("tenant_id")
    applied = apply_subscription_snapshot(
        db,
        tenant_id=tenant_id,
        stripe_customer_id=subscription.get("customer"),
        stripe_subscription_id=subscription.get("id"),
        plan_code="free",
        status="canceled",
        period_end=_ts_to_dt(subscription.get("current_period_end")) or utc_now(),
        event_created=event_created,
    )
    if tenant_id and applied is not None:
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type="stripe",
            actor_id=subscription.get("id"),
            action="billing.subscription_canceled",
            outcome="success",
            resource_type="plan",
            resource_id="free",
        )


def handle_invoice_payment_succeeded(
    db: Session,
    invoice: Dict[str, Any],
    *,
    event_created: Optional[int] = None,
) -> None:
    sub_id = invoice.get("subscription")
    customer_id = invoice.get("customer")
    metadata = invoice.get("subscription_details", {}).get("metadata") or invoice.get("metadata") or {}
    tenant_id = metadata.get("tenant_id")
    applied = apply_subscription_snapshot(
        db,
        tenant_id=tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=sub_id if isinstance(sub_id, str) else None,
        plan_code=metadata.get("plan_code"),
        status="active",
        period_end=_ts_to_dt(invoice.get("period_end") or invoice.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")),
        event_created=event_created,
    )
    if tenant_id and applied is not None:
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type="stripe",
            actor_id=invoice.get("id"),
            action="billing.invoice_payment_succeeded",
            outcome="success",
            resource_type="invoice",
            resource_id=invoice.get("id"),
        )


def handle_invoice_payment_failed(
    db: Session,
    invoice: Dict[str, Any],
    *,
    event_created: Optional[int] = None,
) -> None:
    sub_id = invoice.get("subscription")
    customer_id = invoice.get("customer")
    metadata = invoice.get("subscription_details", {}).get("metadata") or invoice.get("metadata") or {}
    tenant_id = metadata.get("tenant_id")
    applied = apply_subscription_snapshot(
        db,
        tenant_id=tenant_id,
        stripe_customer_id=customer_id,
        stripe_subscription_id=sub_id if isinstance(sub_id, str) else None,
        plan_code=metadata.get("plan_code"),
        status="past_due",
        event_created=event_created,
    )
    if tenant_id and applied is not None:
        record_audit(
            db,
            tenant_id=tenant_id,
            actor_type="stripe",
            actor_id=invoice.get("id"),
            action="billing.invoice_payment_failed",
            outcome="failure",
            resource_type="invoice",
            resource_id=invoice.get("id"),
        )


def process_stripe_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a verified Stripe event idempotently in an independent DB session.

    Must open its own session: FastAPI closes the request-scoped session before
    BackgroundTasks run. Never raises for business skips (duplicates / stale).
    """
    db = create_session()
    try:
        return _process_stripe_event(db, event)
    except Exception:
        db.rollback()
        logger.exception(
            "stripe_webhook_processing_failed event_id=%s type=%s",
            event.get("id") if isinstance(event, dict) else getattr(event, "id", None),
            event.get("type") if isinstance(event, dict) else getattr(event, "type", None),
        )
        raise
    finally:
        db.close()


def _event_get(event: Any, key: str, default: Any = None) -> Any:
    if isinstance(event, dict):
        return event.get(key, default)
    return getattr(event, key, default) if hasattr(event, key) else (
        event.get(key, default) if hasattr(event, "get") else default
    )


def _process_stripe_event(db: Session, event: Any) -> Dict[str, Any]:
    event_id = _event_get(event, "id") or ""
    event_type = _event_get(event, "type") or ""
    event_created = _event_get(event, "created")
    if event_created is not None:
        try:
            event_created = int(event_created)
        except (TypeError, ValueError):
            event_created = None

    if not _claim_event(db, event_id, event_type):
        logger.info("stripe_webhook_duplicate event_id=%s type=%s", event_id, event_type)
        db.commit()
        return {"received": True, "duplicate": True}

    data = _event_get(event, "data") or {}
    if hasattr(data, "get"):
        payload = data.get("object") or {}
    else:
        payload = getattr(data, "object", None) or {}
    if hasattr(payload, "to_dict"):
        payload = payload.to_dict()
    elif not isinstance(payload, dict) and hasattr(payload, "keys"):
        payload = dict(payload)

    if event_type == "checkout.session.completed":
        handle_checkout_session_completed(db, payload, event_created=event_created)
    elif event_type == "customer.subscription.updated":
        handle_subscription_updated(db, payload, event_created=event_created)
    elif event_type == "customer.subscription.deleted":
        handle_subscription_deleted(db, payload, event_created=event_created)
    elif event_type == "invoice.payment_succeeded":
        handle_invoice_payment_succeeded(db, payload, event_created=event_created)
    elif event_type == "invoice.payment_failed":
        handle_invoice_payment_failed(db, payload, event_created=event_created)
    else:
        logger.info("stripe_webhook_ignored type=%s event_id=%s", event_type, event_id)

    db.commit()
    return {"received": True, "duplicate": False, "type": event_type}
