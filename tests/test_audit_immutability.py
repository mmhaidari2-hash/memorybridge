"""Regression tests for audit immutability and metering locks."""

import base64
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))
os.environ.setdefault("SERVICE_API_KEYS", "mbs_test_service_key_abcdefghijklmnopqrstuvwxyz")
os.environ.setdefault("TOKEN_HASH_PEPPER", base64.b64encode(b"p" * 32).decode("ascii"))

from app.models import AuditEvent, Tenant
from sqlalchemy.orm.collections import attribute_mapped_collection  # noqa: F401


def test_audit_event_foreign_key_is_not_cascade_delete():
    fk = next(iter(AuditEvent.__table__.c.tenant_id.foreign_keys))
    assert fk.ondelete is None or str(fk.ondelete).upper() != "CASCADE"


def test_tenant_audit_relationship_does_not_orphan_delete():
    cascade = Tenant.audit_events.property.cascade
    assert not cascade.delete
    assert not cascade.delete_orphan
