"""Stripe checkout + webhook helpers. Optional until STRIPE_SECRET_KEY is set."""

from __future__ import annotations

from typing import Any, Dict, Optional

import stripe
from fastapi import HTTPException, Request

from app.config import get_settings


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
