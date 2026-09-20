"""Append-only audit events. Never store tokens, keys, or memory content.

Audit writes are autonomous: they use a dedicated short-lived DB session so a
rollback of the caller's business transaction cannot erase security logs.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.orm import Session

from app import database as db_module
from app.models import AuditEvent

logger = logging.getLogger("memorybridge.audit")


def record_audit(
    db: Session | None = None,
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
    """Persist an audit row in an isolated transaction.

    ``db`` is accepted for call-site compatibility but is intentionally unused for
    the write path — audits must survive caller rollbacks.
    """
    del db  # autonomous write; ignore caller's session
    # Fresh session from the active factory (tests rebind to the same engine).
    audit_db = db_module.create_session()
    try:
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
        audit_db.add(event)
        audit_db.commit()
    except Exception:
        audit_db.rollback()
        logger.exception(
            "audit_write_failed tenant_id=%s action=%s outcome=%s",
            tenant_id,
            action,
            outcome,
        )
        return
    finally:
        audit_db.close()

    logger.info(
        "audit action=%s outcome=%s tenant_id=%s actor_type=%s resource_type=%s request_id=%s",
        action,
        outcome,
        tenant_id,
        actor_type,
        resource_type,
        request_id,
    )
