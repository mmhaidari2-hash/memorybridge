"""Add tenants.deleted_at for soft-delete (audit FK stays RESTRICT).

Revision ID: 0005_tenant_soft_delete
Revises: 0004_immutable_audit_logs
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_tenant_soft_delete"
down_revision = "0004_immutable_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.add_column(sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tenants") as batch_op:
        batch_op.drop_column("deleted_at")
