"""Append-only audit events. Never store tokens, keys, or memory content."""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app.models import AuditEvent

logger = logging.getLogger("memorybridge.audit")


def record_audit(
    db: Session,
    *,
    tenant_id: str,
    actor_type: str,
    actor_id: Optional[str],
    action: str,
    outcome: str,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        request_id=request_id,
    )
    db.add(event)
    try:
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            "audit_write_failed tenant_id=%s action=%s outcome=%s",
            tenant_id,
            action,
            outcome,
        )
        return

    logger.info(
        "audit action=%s outcome=%s tenant_id=%s actor_type=%s resource_type=%s request_id=%s",
        action,
        outcome,
        tenant_id,
        actor_type,
        resource_type,
        request_id,
    )
