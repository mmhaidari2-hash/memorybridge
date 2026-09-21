import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    slug = Column(String(100), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, default=utc_now, nullable=False)
    # Soft-delete timestamp. Physical DELETE is forbidden while audit rows exist.
    deleted_at = Column(DateTime, nullable=True)

    users = relationship("User", back_populates="tenant", cascade="all, delete-orphan")
    api_keys = relationship("ServiceApiKey", back_populates="tenant", cascade="all, delete-orphan")
    memories = relationship("MemoryRecord", back_populates="tenant", cascade="all, delete-orphan")
    # No cascade: audit rows must survive tenant deletion (immutable compliance trail).
    audit_events = relationship("AuditEvent", back_populates="tenant")
    subscription = relationship(
        "TenantSubscription",
        back_populates="tenant",
        uselist=False,
        cascade="all, delete-orphan",
    )
    usage_counters = relationship(
        "UsageCounter",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )


class ServiceApiKey(Base):
    __tablename__ = "service_api_keys"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(200), nullable=False)
    key_prefix = Column(String(16), nullable=False, index=True)
    key_hash = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(String(32), nullable=False, default="active")
    created_at = Column(DateTime, default=utc_now, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    last_used_at = Column(DateTime, nullable=True)

    tenant = relationship("Tenant", back_populates="api_keys")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_token_hash", name="uq_users_tenant_token_hash"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_token_hash = Column(String(64), nullable=False, index=True)
    full_name = Column(String(200), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    tenant = relationship("Tenant", back_populates="users")
    memories = relationship("MemoryRecord", back_populates="user", cascade="all, delete-orphan")


class MemoryRecord(Base):
    __tablename__ = "memory_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "session_token_hash",
            name="uq_memory_tenant_user_session",
        ),
        Index("ix_memory_tenant_user", "tenant_id", "user_id"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token_hash = Column(String(64), nullable=False, index=True)
    stage = Column(String(100), nullable=True)
    encrypted_content = Column(Text, nullable=False)
    key_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant", back_populates="memories")
    user = relationship("User", back_populates="memories")


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_tenant_created", "tenant_id", "created_at"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    # RESTRICT (default): tenant delete must not wipe the audit trail.
    tenant_id = Column(
        String,
        ForeignKey("tenants.id"),
        nullable=False,
        index=True,
    )
    actor_type = Column(String(32), nullable=False)
    actor_id = Column(String(64), nullable=True)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=True)
    resource_id = Column(String(64), nullable=True)
    outcome = Column(String(32), nullable=False)
    request_id = Column(String(64), nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)

    tenant = relationship("Tenant", back_populates="audit_events")


class Plan(Base):
    """Sellable commercial plan with hard monthly quotas."""

    __tablename__ = "plans"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    code = Column(String(64), unique=True, nullable=False, index=True)
    name = Column(String(120), nullable=False)
    monthly_price_cents = Column(Integer, nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="usd")
    monthly_ops_limit = Column(Integer, nullable=False)
    max_memories = Column(Integer, nullable=False)
    stripe_price_id = Column(String(120), nullable=True)
    is_public = Column(Integer, nullable=False, default=1)  # 1/0 for SQLite-friendly bool
    created_at = Column(DateTime, default=utc_now, nullable=False)

    subscriptions = relationship("TenantSubscription", back_populates="plan")


class TenantSubscription(Base):
    __tablename__ = "tenant_subscriptions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    plan_id = Column(String, ForeignKey("plans.id"), nullable=False, index=True)
    status = Column(String(32), nullable=False, default="active")  # active|past_due|canceled
    stripe_customer_id = Column(String(120), nullable=True, index=True)
    stripe_subscription_id = Column(String(120), nullable=True, index=True)
    current_period_start = Column(DateTime, nullable=False, default=utc_now)
    current_period_end = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant", back_populates="subscription")
    plan = relationship("Plan", back_populates="subscriptions")


class UsageCounter(Base):
    """Monthly usage bucket per tenant. Period key format: YYYY-MM (UTC)."""

    __tablename__ = "usage_counters"
    __table_args__ = (
        UniqueConstraint("tenant_id", "period_key", name="uq_usage_tenant_period"),
    )

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(
        String,
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period_key = Column(String(7), nullable=False, index=True)
    ops_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    tenant = relationship("Tenant", back_populates="usage_counters")


class StripeWebhookEvent(Base):
    """Processed Stripe event IDs for idempotent webhook handling."""

    __tablename__ = "stripe_webhook_events"

    id = Column(String, primary_key=True)  # Stripe evt_...
    event_type = Column(String(64), nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
