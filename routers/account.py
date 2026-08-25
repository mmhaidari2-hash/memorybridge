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
    usage_used: int
    usage_limit: int
    usage_remaining: int
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
    return AccountStatus(
        tenant_id=tenant.id,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        plan=tenant.plan,
        subscription_status=tenant.subscription_status,
        usage_used=usage["used"],
        usage_limit=usage["limit"],
        usage_remaining=usage["remaining"],
        usage_period_start=usage["period_start"],
    )
