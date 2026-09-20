import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.billing import assign_plan, ensure_subscription, get_billing_snapshot
from app.config import api_key_prefix, hash_service_api_key
from app.database import get_db
from app.models import ServiceApiKey, Tenant, utc_now
from app.schemas import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
    AssignPlanRequest,
    BillingStatusResponse,
    TenantCreate,
    TenantResponse,
)
from app.service_auth import verify_admin_api_key

router = APIRouter(tags=["Admin"], prefix="/admin")


@router.post("/tenants", response_model=TenantResponse, status_code=201)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_api_key),
):
    tenant = Tenant(name=payload.name, slug=payload.slug, status="active")
    db.add(tenant)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Tenant slug already exists") from None
    db.refresh(tenant)
    ensure_subscription(db, tenant.id, plan_code="free")

    record_audit(
        db,
        tenant_id=tenant.id,
        actor_type="admin",
        actor_id="admin",
        action="admin.tenant_create",
        outcome="success",
        resource_type="tenant",
        resource_id=tenant.id,
    )

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        deleted_at=None,
    )


@router.post(
    "/tenants/{tenant_id}/keys",
    response_model=ApiKeyCreatedResponse,
    status_code=201,
)
def create_tenant_api_key(
    tenant_id: str,
    payload: ApiKeyCreate,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_api_key),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status != "active":
        raise HTTPException(status_code=403, detail="Tenant is not active")

    plaintext = f"mbs_{secrets.token_urlsafe(32)}"
    key = ServiceApiKey(
        tenant_id=tenant.id,
        name=payload.name,
        key_prefix=api_key_prefix(plaintext),
        key_hash=hash_service_api_key(plaintext),
        status="active",
    )
    db.add(key)
    db.commit()
    db.refresh(key)

    record_audit(
        db,
        tenant_id=tenant.id,
        actor_type="admin",
        actor_id="admin",
        action="admin.api_key_create",
        outcome="success",
        resource_type="service_api_key",
        resource_id=key.id,
    )

    return ApiKeyCreatedResponse(
        id=key.id,
        tenant_id=key.tenant_id,
        name=key.name,
        key_prefix=key.key_prefix,
        api_key=plaintext,
        status=key.status,
    )


@router.post("/keys/{key_id}/revoke", response_model=ApiKeyResponse)
def revoke_api_key(
    key_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_api_key),
):
    key = db.query(ServiceApiKey).filter(ServiceApiKey.id == key_id).first()
    if not key:
        raise HTTPException(status_code=404, detail="API key not found")

    if key.status != "revoked":
        key.status = "revoked"
        key.revoked_at = utc_now()
        db.commit()
        db.refresh(key)

    record_audit(
        db,
        tenant_id=key.tenant_id,
        actor_type="admin",
        actor_id="admin",
        action="admin.api_key_revoke",
        outcome="success",
        resource_type="service_api_key",
        resource_id=key.id,
    )

    return ApiKeyResponse(
        id=key.id,
        tenant_id=key.tenant_id,
        name=key.name,
        key_prefix=key.key_prefix,
        status=key.status,
        created_at=key.created_at.isoformat() + "Z",
        revoked_at=key.revoked_at.isoformat() + "Z" if key.revoked_at else None,
        last_used_at=key.last_used_at.isoformat() + "Z" if key.last_used_at else None,
    )


@router.post("/tenants/{tenant_id}/suspend", response_model=TenantResponse)
def suspend_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_api_key),
):
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status == "deleted":
        raise HTTPException(status_code=409, detail="Tenant is already deleted")

    tenant.status = "suspended"
    # Invalidate active API keys so suspended tenants cannot keep calling.
    for key in tenant.api_keys:
        if key.status == "active":
            key.status = "suspended"
            key.revoked_at = utc_now()
    db.commit()
    db.refresh(tenant)

    record_audit(
        db,
        tenant_id=tenant.id,
        actor_type="admin",
        actor_id="admin",
        action="admin.tenant_suspend",
        outcome="success",
        resource_type="tenant",
        resource_id=tenant.id,
    )

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        deleted_at=tenant.deleted_at.isoformat() + "Z" if tenant.deleted_at else None,
    )


@router.post("/tenants/{tenant_id}/delete", response_model=TenantResponse)
def soft_delete_tenant(
    tenant_id: str,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_api_key),
):
    """Soft-delete a tenant. Rows stay so immutable audit FKs remain valid.

    Physical DELETE is intentionally unsupported while audit_events reference
    the tenant (RESTRICT / no CASCADE). The slug is rewritten so a future
    company can re-register the original brand slug.
    """
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status == "deleted":
        return TenantResponse(
            id=tenant.id,
            name=tenant.name,
            slug=tenant.slug,
            status=tenant.status,
            deleted_at=tenant.deleted_at.isoformat() + "Z" if tenant.deleted_at else None,
        )

    stamp = int(utc_now().timestamp())
    suffix = f"-deleted-{stamp}-{secrets.token_hex(4)}"
    base = tenant.slug
    max_base = max(1, 100 - len(suffix))
    if len(base) > max_base:
        base = base[:max_base]
    tenant.slug = f"{base}{suffix}"
    tenant.status = "deleted"
    tenant.deleted_at = utc_now()
    # Revoke all active/suspended keys so soft-deleted tenants cannot authenticate.
    for key in tenant.api_keys:
        if key.status in {"active", "suspended"}:
            key.status = "revoked"
            key.revoked_at = utc_now()
    db.commit()
    db.refresh(tenant)

    record_audit(
        db,
        tenant_id=tenant.id,
        actor_type="admin",
        actor_id="admin",
        action="admin.tenant_soft_delete",
        outcome="success",
        resource_type="tenant",
        resource_id=tenant.id,
    )

    return TenantResponse(
        id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        status=tenant.status,
        deleted_at=tenant.deleted_at.isoformat() + "Z" if tenant.deleted_at else None,
    )


@router.post("/tenants/{tenant_id}/plan", response_model=BillingStatusResponse)
def assign_tenant_plan(
    tenant_id: str,
    payload: AssignPlanRequest,
    db: Session = Depends(get_db),
    _admin: str = Depends(verify_admin_api_key),
):
    """Assign a plan after Stripe payment OR offline/manual payment."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    if tenant.status == "deleted":
        raise HTTPException(status_code=403, detail="Tenant is deleted")

    assign_plan(db, tenant_id, payload.plan_code, status="active")
    record_audit(
        db,
        tenant_id=tenant_id,
        actor_type="admin",
        actor_id="admin",
        action="admin.plan_assign",
        outcome="success",
        resource_type="plan",
        resource_id=payload.plan_code,
    )
    return BillingStatusResponse(**get_billing_snapshot(db, tenant_id))
