from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Tenant, UsageEvent
from app.service_auth import ServiceAuthContext

# Initial commercial limits. These are intentionally centralized so pricing
# experiments do not leak into request handlers.
PLAN_MONTHLY_EVENT_LIMITS = {
    "free": 1_000,
    "pro": 50_000,
    "team": 250_000,
}


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.utcnow()
    return datetime(now.year, now.month, 1)


def get_usage_summary(db: Session, tenant: Tenant) -> dict:
    limit = PLAN_MONTHLY_EVENT_LIMITS.get(tenant.plan)
    if limit is None:
        raise HTTPException(status_code=403, detail="Tenant plan is not enabled")

    used = (
        db.query(func.coalesce(func.sum(UsageEvent.quantity), 0))
        .filter(
            UsageEvent.tenant_id == tenant.id,
            UsageEvent.created_at >= month_start(),
        )
        .scalar()
    )
    used = int(used or 0)
    return {
        "plan": tenant.plan,
        "limit": limit,
        "used": used,
        "remaining": max(limit - used, 0),
        "period_start": month_start(),
    }


def enforce_quota(
    db: Session,
    auth: ServiceAuthContext,
    quantity: int = 1,
) -> None:
    """Reject billable DB-backed traffic that would exceed the tenant plan quota."""
    if auth.tenant_id is None or auth.workspace_id is None:
        return

    tenant = db.get(Tenant, auth.tenant_id)
    if tenant is None or tenant.status != "active":
        raise HTTPException(status_code=403, detail="Tenant is not active")

    summary = get_usage_summary(db, tenant)
    if summary["used"] + quantity > summary["limit"]:
        raise HTTPException(
            status_code=429,
            detail={
                "code": "monthly_quota_exceeded",
                "plan": tenant.plan,
                "limit": summary["limit"],
                "used": summary["used"],
            },
        )
