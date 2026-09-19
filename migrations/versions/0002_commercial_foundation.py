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

DEFAULT_TENANT_ID = "00000000-0000-4000-8000-000000000001"


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

    op.execute(
        sa.text(
            "INSERT INTO tenants (id, name, slug, status, created_at) "
            f"VALUES ('{DEFAULT_TENANT_ID}', 'Default Tenant', 'default', 'active', CURRENT_TIMESTAMP)"
        )
    )

    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.String(), nullable=True))

    op.execute(
        sa.text(
            f"UPDATE users SET tenant_id = '{DEFAULT_TENANT_ID}' WHERE tenant_id IS NULL"
        )
    )

    with op.batch_alter_table("users") as batch_op:
        batch_op.alter_column("tenant_id", existing_type=sa.String(), nullable=False)
        batch_op.create_foreign_key(
            "fk_users_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_users_tenant_id", ["tenant_id"])
        batch_op.drop_index("ix_users_user_token_hash")
        batch_op.create_index("ix_users_user_token_hash", ["user_token_hash"], unique=False)
        batch_op.create_unique_constraint(
            "uq_users_tenant_token_hash",
            ["tenant_id", "user_token_hash"],
        )

    with op.batch_alter_table("memory_records") as batch_op:
        batch_op.add_column(sa.Column("tenant_id", sa.String(), nullable=True))
        batch_op.add_column(
            sa.Column("key_version", sa.Integer(), nullable=False, server_default="1")
        )

    op.execute(
        sa.text(
            f"UPDATE memory_records SET tenant_id = '{DEFAULT_TENANT_ID}' WHERE tenant_id IS NULL"
        )
    )

    with op.batch_alter_table("memory_records") as batch_op:
        batch_op.alter_column("tenant_id", existing_type=sa.String(), nullable=False)
        batch_op.create_foreign_key(
            "fk_memory_records_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_index("ix_memory_records_tenant_id", ["tenant_id"])
        batch_op.create_index("ix_memory_tenant_user", ["tenant_id", "user_id"])
        batch_op.create_unique_constraint(
            "uq_memory_tenant_user_session",
            ["tenant_id", "user_id", "session_token_hash"],
        )
        batch_op.alter_column("key_version", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("memory_records") as batch_op:
        batch_op.drop_constraint("uq_memory_tenant_user_session", type_="unique")
        batch_op.drop_index("ix_memory_tenant_user")
        batch_op.drop_index("ix_memory_records_tenant_id")
        batch_op.drop_constraint("fk_memory_records_tenant_id", type_="foreignkey")
        batch_op.drop_column("key_version")
        batch_op.drop_column("tenant_id")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("uq_users_tenant_token_hash", type_="unique")
        batch_op.drop_index("ix_users_tenant_id")
        batch_op.drop_constraint("fk_users_tenant_id", type_="foreignkey")
        batch_op.drop_index("ix_users_user_token_hash")
        batch_op.create_index("ix_users_user_token_hash", ["user_token_hash"], unique=True)
        batch_op.drop_column("tenant_id")

    op.drop_index("ix_audit_tenant_created", table_name="audit_events")
    op.drop_index("ix_audit_events_tenant_id", table_name="audit_events")
    op.drop_table("audit_events")

    op.drop_index("ix_service_api_keys_key_hash", table_name="service_api_keys")
    op.drop_index("ix_service_api_keys_key_prefix", table_name="service_api_keys")
    op.drop_index("ix_service_api_keys_tenant_id", table_name="service_api_keys")
    op.drop_table("service_api_keys")

    op.drop_index("ix_tenants_slug", table_name="tenants")
    op.drop_table("tenants")
