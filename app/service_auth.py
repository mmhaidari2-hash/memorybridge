import hmac
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth_context import AuthContext
from app.config import api_key_prefix, get_settings, hash_service_api_key
from app.database import get_db
from app.models import ServiceApiKey, Tenant, utc_now
from app.rate_limit import rate_limiter
from app.bootstrap import ensure_default_tenant


def _compare_hash(supplied_hash: str, expected_hash: str) -> bool:
    return hmac.compare_digest(supplied_hash, expected_hash)


def verify_service_api_key(
    request: Request,
    x_memorybridge_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> AuthContext:
    if not x_memorybridge_key:
        raise HTTPException(status_code=401, detail="Missing service API key")

    settings = get_settings()
    supplied_hash = hash_service_api_key(x_memorybridge_key)

    # 1) Durable DB-backed keys (revocable).
    db_key = (
        db.query(ServiceApiKey)
        .filter(ServiceApiKey.key_hash == supplied_hash)
        .first()
    )
    if db_key is not None:
        if db_key.status != "active":
            raise HTTPException(status_code=401, detail="Invalid service API key")

        tenant = db.query(Tenant).filter(Tenant.id == db_key.tenant_id).first()
        if tenant is None or tenant.status != "active":
            raise HTTPException(status_code=403, detail="Tenant is not active")

        rate_limiter.check(supplied_hash)
        db_key.last_used_at = utc_now()
        db.add(db_key)
        db.commit()

        ctx = AuthContext(
            tenant_id=tenant.id,
            tenant_slug=tenant.slug,
            key_source="db",
            key_id=db_key.id,
            key_hash=supplied_hash,
            key_prefix=db_key.key_prefix,
        )
        request.state.auth = ctx
        return ctx

    # 2) Bootstrap env keys → default tenant (for initial deploy / CI).
    env_valid = any(
        _compare_hash(supplied_hash, expected)
        for expected in settings.env_service_key_hashes
    )
    if not env_valid:
        raise HTTPException(status_code=401, detail="Invalid service API key")

    tenant = ensure_default_tenant(db)
    if tenant.status != "active":
        raise HTTPException(status_code=403, detail="Tenant is not active")

    rate_limiter.check(supplied_hash)
    ctx = AuthContext(
        tenant_id=tenant.id,
        tenant_slug=tenant.slug,
        key_source="env",
        key_id=None,
        key_hash=supplied_hash,
        key_prefix=api_key_prefix(x_memorybridge_key),
    )
    request.state.auth = ctx
    return ctx


def verify_admin_api_key(
    x_memorybridge_admin_key: Optional[str] = Header(default=None),
) -> str:
    settings = get_settings()
    if settings.admin_api_key_hash is None:
        raise HTTPException(status_code=503, detail="Admin API is not configured")

    if not x_memorybridge_admin_key:
        raise HTTPException(status_code=401, detail="Missing admin API key")

    supplied = hash_service_api_key(x_memorybridge_admin_key)
    if not _compare_hash(supplied, settings.admin_api_key_hash):
        raise HTTPException(status_code=401, detail="Invalid admin API key")

    rate_limiter.check(f"admin:{supplied}")
    return supplied
