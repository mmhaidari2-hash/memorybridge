"""Commercial billing: plans, quotas, usage metering, Stripe checkout."""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime
from typing import Optional, Tuple

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import MemoryRecord, Plan, TenantSubscription, UsageCounter, utc_now

# Default catalog — seeded on first use. Prices are USD monthly.
DEFAULT_PLANS = (
    {
        "code": "free",
        "name": "Free",
        "monthly_price_cents": 0,
        "monthly_ops_limit": 1_000,
        "max_memories": 100,
        "is_public": 1,
    },
    {
        "code": "starter",
        "name": "Starter",
        "monthly_price_cents": 4900,
        "monthly_ops_limit": 50_000,
        "max_memories": 10_000,
        "is_public": 1,
    },
    {
        "code": "growth",
        "name": "Growth",
        "monthly_price_cents": 19900,
        "monthly_ops_limit": 500_000,
        "max_memories": 100_000,
        "is_public": 1,
    },
)


def current_period_key(now: Optional[datetime] = None) -> str:
    stamp = now or utc_now()
    return f"{stamp.year:04d}-{stamp.month:02d}"


def period_bounds(period_key: str) -> Tuple[datetime, datetime]:
    year_s, month_s = period_key.split("-")
    year, month = int(year_s), int(month_s)
    start = datetime(year, month, 1)
    last_day = monthrange(year, month)[1]
    end = datetime(year, month, last_day, 23, 59, 59)
    return start, end


def ensure_plans(db: Session, *, commit: bool = True) -> None:
    settings = get_settings()
    for spec in DEFAULT_PLANS:
        existing = db.query(Plan).filter(Plan.code == spec["code"]).first()
        stripe_price = None
        if spec["code"] == "starter":
            stripe_price = settings.stripe_price_starter or None
        elif spec["code"] == "growth":
            stripe_price = settings.stripe_price_growth or None

        if existing:
            if stripe_price and existing.stripe_price_id != stripe_price:
                existing.stripe_price_id = stripe_price
                db.add(existing)
            continue

        db.add(
            Plan(
                code=spec["code"],
                name=spec["name"],
                monthly_price_cents=spec["monthly_price_cents"],
                monthly_ops_limit=spec["monthly_ops_limit"],
                max_memories=spec["max_memories"],
                stripe_price_id=stripe_price,
                is_public=spec["is_public"],
            )
        )
    if commit:
        db.commit()
    else:
        db.flush()


def get_plan_by_code(db: Session, code: str) -> Plan:
    ensure_plans(db)
    plan = db.query(Plan).filter(Plan.code == code).first()
    if not plan:
        raise HTTPException(status_code=404, detail=f"Unknown plan: {code}")
    return plan


def ensure_subscription(
    db: Session,
    tenant_id: str,
    plan_code: str = "free",
    *,
    commit: bool = True,
) -> TenantSubscription:
    ensure_plans(db, commit=commit)
    sub = (
        db.query(TenantSubscription)
        .filter(TenantSubscription.tenant_id == tenant_id)
        .first()
    )
    if sub:
        return sub

    plan = db.query(Plan).filter(Plan.code == plan_code).first()
    if plan is None:
        raise HTTPException(status_code=404, detail=f"Unknown plan: {plan_code}")

    period_key = current_period_key()
    start, end = period_bounds(period_key)
    sub = TenantSubscription(
        tenant_id=tenant_id,
        plan_id=plan.id,
        status="active",
        current_period_start=start,
        current_period_end=end,
    )
    db.add(sub)
    if commit:
        db.commit()
        db.refresh(sub)
    else:
        db.flush()
    return sub


def assign_plan(
    db: Session,
    tenant_id: str,
    plan_code: str,
    *,
    stripe_customer_id: Optional[str] = None,
    stripe_subscription_id: Optional[str] = None,
    status: str = "active",
) -> TenantSubscription:
    plan = get_plan_by_code(db, plan_code)
    sub = ensure_subscription(db, tenant_id)
    sub.plan_id = plan.id
    sub.status = status
    if stripe_customer_id is not None:
        sub.stripe_customer_id = stripe_customer_id
    if stripe_subscription_id is not None:
        sub.stripe_subscription_id = stripe_subscription_id
    period_key = current_period_key()
    start, end = period_bounds(period_key)
    sub.current_period_start = start
    sub.current_period_end = end
    sub.updated_at = utc_now()
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def _get_usage(db: Session, tenant_id: str, period_key: str) -> UsageCounter:
    row = (
        db.query(UsageCounter)
        .filter(
            UsageCounter.tenant_id == tenant_id,
            UsageCounter.period_key == period_key,
        )
        .first()
    )
    if row:
        return row
    row = UsageCounter(tenant_id=tenant_id, period_key=period_key, ops_count=0)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _get_usage_for_update(db: Session, tenant_id: str, period_key: str) -> UsageCounter:
    """Load the monthly usage row under a row-level lock.

    Concurrent callers serialize on the same (tenant_id, period_key) row so
    ops_count increments cannot race past the plan quota.
    """

    def _locked() -> UsageCounter | None:
        return (
            db.query(UsageCounter)
            .filter(
                UsageCounter.tenant_id == tenant_id,
                UsageCounter.period_key == period_key,
            )
            .with_for_update()
            .first()
        )

    row = _locked()
    if row:
        return row

    candidate = UsageCounter(tenant_id=tenant_id, period_key=period_key, ops_count=0)
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
    except IntegrityError:
        # Another worker inserted the same period bucket first — lock that row.
        row = _locked()
        if row is None:
            raise
        return row

    locked = _locked()
    return locked if locked is not None else candidate


def get_billing_snapshot(db: Session, tenant_id: str) -> dict:
    sub = ensure_subscription(db, tenant_id)
    plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
    period_key = current_period_key()
    usage = _get_usage(db, tenant_id, period_key)
    memory_count = (
        db.query(MemoryRecord)
        .filter(MemoryRecord.tenant_id == tenant_id)
        .count()
    )
    ops_remaining = max(0, plan.monthly_ops_limit - usage.ops_count)
    memories_remaining = max(0, plan.max_memories - memory_count)
    return {
        "tenant_id": tenant_id,
        "plan_code": plan.code,
        "plan_name": plan.name,
        "status": sub.status,
        "monthly_price_cents": plan.monthly_price_cents,
        "currency": plan.currency,
        "period_key": period_key,
        "ops_used": usage.ops_count,
        "ops_limit": plan.monthly_ops_limit,
        "ops_remaining": ops_remaining,
        "memories_used": memory_count,
        "memories_limit": plan.max_memories,
        "memories_remaining": memories_remaining,
        "upgrade_required": ops_remaining == 0 or memories_remaining == 0,
    }


def enforce_and_meter(db: Session, tenant_id: str, *, creating_memory: bool = False) -> None:
    """Reserve one billable op inside the caller's open transaction.

    Does NOT commit. Callers must commit after the business write succeeds so a
    failed insert/update cannot burn quota (atomic metering + data mutation).
    Raises HTTP 402 so clients know this is a payment/plan problem, not auth.
    """
    sub = ensure_subscription(db, tenant_id, commit=False)
    if sub.status not in {"active", "trialing"}:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "subscription_inactive",
                "message": "Subscription is not active. Update billing to continue.",
                "status": sub.status,
            },
        )

    plan = db.query(Plan).filter(Plan.id == sub.plan_id).one()
    period_key = current_period_key()
    usage = _get_usage_for_update(db, tenant_id, period_key)

    if usage.ops_count >= plan.monthly_ops_limit:
        raise HTTPException(
            status_code=402,
            detail={
                "error": "ops_quota_exceeded",
                "message": "Monthly API operation quota exceeded. Upgrade your plan.",
                "plan_code": plan.code,
                "ops_limit": plan.monthly_ops_limit,
                "ops_used": usage.ops_count,
                "upgrade": "/v1/billing/checkout",
            },
        )

    if creating_memory:
        memory_count = (
            db.query(MemoryRecord)
            .filter(MemoryRecord.tenant_id == tenant_id)
            .count()
        )
        if memory_count >= plan.max_memories:
            raise HTTPException(
                status_code=402,
                detail={
                    "error": "memory_quota_exceeded",
                    "message": "Stored memory quota exceeded. Upgrade your plan.",
                    "plan_code": plan.code,
                    "memories_limit": plan.max_memories,
                    "memories_used": memory_count,
                    "upgrade": "/v1/billing/checkout",
                },
            )

    usage.ops_count += 1
    usage.updated_at = utc_now()
    db.add(usage)
    db.flush()
