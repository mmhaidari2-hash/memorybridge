"""Ensure the default tenant exists for env-bootstrap service keys."""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Tenant

logger = logging.getLogger("memorybridge.bootstrap")

DEFAULT_TENANT_NAME = "Default Tenant"


def ensure_default_tenant(db: Session) -> Tenant:
    settings = get_settings()
    tenant = db.query(Tenant).filter(Tenant.slug == settings.default_tenant_slug).first()
    if tenant:
        return tenant

    tenant = Tenant(
        name=DEFAULT_TENANT_NAME,
        slug=settings.default_tenant_slug,
        status="active",
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    logger.info("bootstrap_default_tenant_created slug=%s id=%s", tenant.slug, tenant.id)
    return tenant
