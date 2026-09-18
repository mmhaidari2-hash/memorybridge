import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
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
from app.config import api_key_prefix, get_settings, hash_service_api_key
from app.database import get_db
from app.models import Plan, ServiceApiKey, Tenant
from app.rate_limit import rate_limiter
from app.schemas import (
    BillingConfigResponse,
    BillingStatusResponse,
    CheckoutRequest,
    CheckoutResponse,
    PlanInfo,
    SignupRequest,
    SignupResponse,
)
from app.service_auth import verify_service_api_key
from app import stripe_billing

router = APIRouter(tags=["Billing"])

RESERVED_SLUGS = frozenset(
    {
        "default",
        "admin",
        "api",
        "www",
        "billing",
        "health",
        "ready",
        "metrics",
        "assets",
        "v1",
    }
)
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@router.get("/billing/config", response_model=BillingConfigResponse)
def billing_config():
    settings = get_settings()
    return BillingConfigResponse(
        stripe_enabled=stripe_billing.stripe_enabled()
        and bool(settings.stripe_price_starter)
        and bool(settings.stripe_price_growth),
        public_plans=["free", "starter", "growth"],
        signup_enabled=True,
    )


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


@router.post("/billing/signup", response_model=SignupResponse, status_code=201)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)):
    """Public self-serve signup: create tenant + API key, optionally start Stripe Checkout."""
    client_host = request.client.host if request.client else "unknown"
    rate_limiter.check(f"signup:{client_host}")

    if payload.slug in RESERVED_SLUGS:
        raise HTTPException(status_code=400, detail="Slug is reserved")
    if not EMAIL_RE.match(payload.email):
        raise HTTPException(status_code=400, detail="Invalid email")

    ensure_plans(db)

    wants_paid = payload.plan_code in {"starter", "growth"}
    if wants_paid:
        plan = get_plan_by_code(db, payload.plan_code)
        if not stripe_billing.stripe_enabled() or not plan.stripe_price_id:
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "card_payments_not_configured",
                    "message": "Card checkout is not configured yet. Choose Free, or ask an admin to assign a paid plan offline.",
                },
            )

    tenant = Tenant(name=payload.company_name, slug=payload.slug, status="active")
    db.add(tenant)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Company slug already exists") from None
    db.refresh(tenant)

    # Always start on Free until Stripe confirms payment (or stay Free).
    ensure_subscription(db, tenant.id, plan_code="free")

    plaintext_key = f"mbs_{secrets.token_urlsafe(32)}"
    key = ServiceApiKey(
        tenant_id=tenant.id,
        name="default",
        key_prefix=api_key_prefix(plaintext_key),
        key_hash=hash_service_api_key(plaintext_key),
        status="active",
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    checkout_url = None
    session_id = None
    message = "Tenant created on Free plan. Store your API key now — it will not be shown again."

    if wants_paid:
        plan = get_plan_by_code(db, payload.plan_code)
        session = stripe_billing.create_checkout_session(
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            plan_code=plan.code,
            stripe_price_id=plan.stripe_price_id,
            customer_email=payload.email,
        )
        checkout_url = session["checkout_url"]
        session_id = session["session_id"]
        message = (
            "Tenant created. Complete card checkout to activate the paid plan. "
            "Your API key works now on Free limits until payment succeeds."
        )

    record_audit(
        db,
        tenant_id=tenant.id,
        actor_type="signup",
        actor_id=payload.email[:64],
        action="billing.signup",
        outcome="success",
        resource_type="tenant",
        resource_id=tenant.id,
        request_id=request.headers.get("X-Request-ID"),
    )

    return SignupResponse(
        tenant_id=tenant.id,
        slug=tenant.slug,
        plan_code="free" if not wants_paid else payload.plan_code,
        api_key=plaintext_key,
        checkout_url=checkout_url,
        session_id=session_id,
        message=message,
    )


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
    if not plan.stripe_price_id or not stripe_billing.stripe_enabled():
        raise HTTPException(
            status_code=503,
            detail={
                "error": "card_payments_not_configured",
                "message": f"Plan '{plan.code}' card checkout is not configured.",
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
