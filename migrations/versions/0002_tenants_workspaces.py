"""add tenants and workspaces

Revision ID: 0002_tenants_workspaces
Revises: 0001_secure_foundation
"""

from alembic import op
import sqlalchemy as sa

revision = "0002_tenants_workspaces"
down_revision = "0001_secure_foundation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tenants",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("plan", sa.String(), nullable=False, server_default="free"),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_workspace_tenant_slug"),
    )
    op.create_index("ix_workspaces_tenant_id", "workspaces", ["tenant_id"])

    # Nullable during the compatibility transition. A later migration will
    # backfill existing users and then enforce NOT NULL.
    op.add_column("users", sa.Column("workspace_id", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_users_workspace_id",
        "users",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_users_workspace_id", "users", ["workspace_id"])


def downgrade():
    op.drop_index("ix_users_workspace_id", table_name="users")
    op.drop_constraint("fk_users_workspace_id", "users", type_="foreignkey")
    op.drop_column("users", "workspace_id")
    op.drop_index("ix_workspaces_tenant_id", table_name="workspaces")
    op.drop_table("workspaces")
    op.drop_table("tenants")
