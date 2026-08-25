from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant, Workspace
from app.quota import get_usage_summary
from app.service_auth import ServiceAuthContext, verify_service_api_key

router = APIRouter(tags=["Account"])


class AccountStatus(BaseModel):
    tenant_id: str
    workspace_id: str
    workspace_name: str
    plan: str
    subscription_status: str | None
    paid_entitlement_active: bool
    can_upgrade: bool
    usage_used: int
    usage_limit: int
    usage_remaining: int
    usage_percent: float
    usage_period_start: datetime


@router.get("/account/status", response_model=AccountStatus)
def account_status(
    db: Session = Depends(get_db),
    auth: ServiceAuthContext = Depends(verify_service_api_key),
):
    if auth.tenant_id is None or auth.workspace_id is None:
        raise HTTPException(status_code=403, detail="Workspace API key required")

    tenant = db.get(Tenant, auth.tenant_id)
    workspace = db.get(Workspace, auth.workspace_id)
    if tenant is None or workspace is None or workspace.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="Account context not found")

    usage = get_usage_summary(db, tenant)
    paid_entitlement_active = tenant.plan in {"pro", "team"} and tenant.subscription_status in {"active", "trialing"}
    usage_percent = round((usage["used"] / usage["limit"]) * 100, 2) if usage["limit"] else 0.0

    return AccountStatus(
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        plan=tenant.plan,
        subscription_status=tenant.subscription_status,
        paid_entitlement_active=paid_entitlement_active,
        can_upgrade=tenant.plan == "free",
        usage_used=usage["used"],
        usage_limit=usage["limit"],
        usage_remaining=usage["remaining"],
        usage_percent=usage_percent,
        usage_period_start=usage["period_start"],
    )
