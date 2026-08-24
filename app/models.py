import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.database import Base


class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    plan = Column(String, nullable=False, default="free")
    status = Column(String, nullable=False, default="active")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workspaces = relationship("Workspace", back_populates="tenant", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uq_workspace_tenant_slug"),)

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    slug = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    tenant = relationship("Tenant", back_populates="workspaces")
    users = relationship("User", back_populates="workspace", cascade="all, delete-orphan")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True)
    user_token_hash = Column(String(64), unique=True, index=True, nullable=False)
    full_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="users")
    memories = relationship("MemoryRecord", back_populates="user", cascade="all, delete-orphan")


class MemoryRecord(Base):
    __tablename__ = "memory_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_token_hash = Column(String(64), index=True, nullable=False)
    stage = Column(String, nullable=True)
    encrypted_content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    user = relationship("User", back_populates="memories")
