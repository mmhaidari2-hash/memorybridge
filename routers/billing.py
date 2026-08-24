import os

import stripe
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.billing import configure_stripe, price_id_for_plan
from app.database import get_db
from app.models import Tenant
from app.service_auth import ServiceAuthContext, verify_service_api_key

router = APIRouter(tags=["Billing"])


class CheckoutRequest(BaseModel):
    plan: str


class CheckoutResponse(BaseModel):
    checkout_url: str
    session_id: str


@router.post("/billing/checkout", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
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
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url=success_url,
            cancel_url=cancel_url,
            client_reference_id=tenant.id,
            metadata={"tenant_id": tenant.id, "plan": payload.plan},
            subscription_data={"metadata": {"tenant_id": tenant.id, "plan": payload.plan}},
        )
    except stripe.StripeError as exc:
        raise HTTPException(status_code=502, detail="Billing provider error") from exc

    if not session.url:
        raise HTTPException(status_code=502, detail="Billing provider did not return a checkout URL")

    return CheckoutResponse(checkout_url=session.url, session_id=session.id)
