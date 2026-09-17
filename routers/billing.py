from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.auth_context import AuthContext
from app.billing import (
    assign_plan,
    ensure_plans,
    ensure_subscription,
    get_billing_snapshot,
    get_plan_by_code,
)
from app.database import get_db
from app.models import Plan, Tenant
from app.schemas import (
    BillingStatusResponse,
    CheckoutRequest,
    CheckoutResponse,
    PlanInfo,
)
from app.service_auth import verify_service_api_key
from app import stripe_billing

router = APIRouter(tags=["Billing"])


@router.get("/billing/plans", response_model=list[PlanInfo])
def list_public_plans(db: Session = Depends(get_db)):
    ensure_plans(db)
    plans = (
        db.query(Plan)
        .filter(Plan.is_public == 1)
        .order_by(Plan.monthly_price_cents.asc())
        .all()
    )
    return [
        PlanInfo(
            code=p.code,
            name=p.name,
            monthly_price_cents=p.monthly_price_cents,
            currency=p.currency,
            monthly_ops_limit=p.monthly_ops_limit,
            max_memories=p.max_memories,
        )
        for p in plans
    ]


@router.get("/billing/status", response_model=BillingStatusResponse)
def billing_status(
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(verify_service_api_key),
):
    snap = get_billing_snapshot(db, auth.tenant_id)
    return BillingStatusResponse(**snap)


@router.post("/billing/checkout", response_model=CheckoutResponse)
def create_checkout(
    payload: CheckoutRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthContext = Depends(verify_service_api_key),
):
    plan = get_plan_by_code(db, payload.plan_code)
    if not plan.stripe_price_id:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "price_not_configured",
                "message": f"Plan '{plan.code}' has no Stripe price ID configured.",
            },
        )

    sub = ensure_subscription(db, auth.tenant_id)
    tenant = db.query(Tenant).filter(Tenant.id == auth.tenant_id).one()
    session = stripe_billing.create_checkout_session(
        tenant_id=auth.tenant_id,
        tenant_slug=tenant.slug,
        plan_code=plan.code,
        stripe_price_id=plan.stripe_price_id,
        customer_email=payload.customer_email,
        existing_customer_id=sub.stripe_customer_id,
    )

    record_audit(
        db,
        tenant_id=auth.tenant_id,
        actor_type="service_key",
        actor_id=auth.key_id or auth.key_prefix,
        action="billing.checkout_create",
        outcome="success",
        resource_type="plan",
        resource_id=plan.code,
        request_id=request.headers.get("X-Request-ID"),
    )

    return CheckoutResponse(
        checkout_url=session["checkout_url"],
        session_id=session["session_id"],
        plan_code=plan.code,
    )


@router.post("/billing/webhook")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    body, signature = await stripe_billing.read_webhook_payload(request)
    event = stripe_billing.construct_webhook_event(body, signature)

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        metadata = session.get("metadata") or {}
        tenant_id = metadata.get("tenant_id") or session.get("client_reference_id")
        plan_code = metadata.get("plan_code")
        if tenant_id and plan_code:
            assign_plan(
                db,
                tenant_id,
                plan_code,
                stripe_customer_id=session.get("customer"),
                stripe_subscription_id=session.get("subscription"),
                status="active",
            )
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

    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        tenant_id = (subscription.get("metadata") or {}).get("tenant_id")
        if tenant_id:
            # Fall back to free tier so the product keeps working at free limits.
            assign_plan(db, tenant_id, "free", status="active")
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

    return {"received": True}
