import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit import record_audit
from app.config import api_key_prefix, hash_service_api_key
from app.database import get_db
from app.models import ServiceApiKey, Tenant, utc_now
from app.schemas import (
    ApiKeyCreate,
    ApiKeyCreatedResponse,
    ApiKeyResponse,
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

    tenant.status = "suspended"
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
    )
