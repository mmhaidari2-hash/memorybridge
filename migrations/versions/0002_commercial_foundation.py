"""Commercial foundation: tenants, durable API keys, key versions, audit.

Revision ID: 0002_commercial_foundation
Revises: 0001_secure_foundation
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_commercial_foundation"
down_revision = "0001_secure_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_tenants_slug", "tenants", ["slug"], unique=True)

    op.create_table(
        "service_api_keys",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_service_api_keys_tenant_id", "service_api_keys", ["tenant_id"])
    op.create_index("ix_service_api_keys_key_prefix", "service_api_keys", ["key_prefix"])
    op.create_index("ix_service_api_keys_key_hash", "service_api_keys", ["key_hash"], unique=True)

    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("actor_type", sa.String(length=32), nullable=False),
        sa.Column("actor_id", sa.String(length=64), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=True),
        sa.Column("resource_id", sa.String(length=64), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_audit_events_tenant_id", "audit_events", ["tenant_id"])
    op.create_index("ix_audit_tenant_created", "audit_events", ["tenant_id", "created_at"])

    # Seed a default tenant and backfill existing rows.
    op.execute(
        sa.text(
            "INSERT INTO tenants (id, name, slug, status, created_at) "
            "VALUES ('00000000-0000-4000-8000-000000000001', 'Default Tenant', 'default', 'active', CURRENT_TIMESTAMP)"
        )
    )

    op.add_column("users", sa.Column("tenant_id", sa.String(), nullable=True))
    op.execute(
        sa.text(
            "UPDATE users SET tenant_id = '00000000-0000-4000-8000-000000000001' "
            "WHERE tenant_id IS NULL"
        )
    )
    op.alter_column("users", "tenant_id", existing_type=sa.String(), nullable=False)
    op.create_foreign_key(
        "fk_users_tenant_id",
        "users",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.drop_index("ix_users_user_token_hash", table_name="users")
    op.create_index("ix_users_user_token_hash", "users", ["user_token_hash"], unique=False)
    op.create_unique_constraint(
        "uq_users_tenant_token_hash",
        "users",
        ["tenant_id", "user_token_hash"],
    )

    op.add_column("memory_records", sa.Column("tenant_id", sa.String(), nullable=True))
    op.add_column(
        "memory_records",
        sa.Column("key_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.execute(
        sa.text(
            "UPDATE memory_records SET tenant_id = '00000000-0000-4000-8000-000000000001' "
            "WHERE tenant_id IS NULL"
        )
    )
    op.alter_column("memory_records", "tenant_id", existing_type=sa.String(), nullable=False)
    op.create_foreign_key(
        "fk_memory_records_tenant_id",
        "memory_records",
        "tenants",
        ["tenant_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_memory_records_tenant_id", "memory_records", ["tenant_id"])
    op.create_index("ix_memory_tenant_user", "memory_records", ["tenant_id", "user_id"])
    op.create_unique_constraint(
        "uq_memory_tenant_user_session",
        "memory_records",
        ["tenant_id", "user_id", "session_token_hash"],
    )
    op.alter_column("memory_records", "key_version", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_memory_tenant_user_session", "memory_records", type_="unique")
    op.drop_index("ix_memory_tenant_user", table_name="memory_records")
    op.drop_index("ix_memory_records_tenant_id", table_name="memory_records")
    op.drop_constraint("fk_memory_records_tenant_id", "memory_records", type_="foreignkey")
    op.drop_column("memory_records", "key_version")
    op.drop_column("memory_records", "tenant_id")

    op.drop_constraint("uq_users_tenant_token_hash", "users", type_="unique")
    op.drop_index("ix_users_tenant_id", table_name="users")
    op.drop_constraint("fk_users_tenant_id", "users", type_="foreignkey")
    op.drop_index("ix_users_user_token_hash", table_name="users")
    op.create_index("ix_users_user_token_hash", "users", ["user_token_hash"], unique=True)
    op.drop_column("users", "tenant_id")

    op.drop_index("ix_audit_tenant_created", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_service_api_keys_key_hash", table_name="service_api_keys")
    op.drop_index("ix_service_api_keys_key_prefix", table_name="service_api_keys")
    op.drop_index("ix_service_api_keys_tenant_id", table_name="service_api_keys")
    op.drop_table("service_api_keys")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
