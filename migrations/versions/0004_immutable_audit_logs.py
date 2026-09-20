"""Make audit_events.tenant_id immutable on tenant delete (no CASCADE).

Revision ID: 0004_immutable_audit_logs
Revises: 0003_billing_foundation
Create Date: 2026-09-20
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_immutable_audit_logs"
down_revision = "0003_billing_foundation"
branch_labels = None
depends_on = None


def _tenant_fk_names(inspector) -> list[str]:
    names: list[str] = []
    for fk in inspector.get_foreign_keys("audit_events"):
        if fk.get("referred_table") == "tenants" and fk.get("name"):
            names.append(fk["name"])
    return names


def upgrade() -> None:
    # Drop CASCADE FK so deleting a tenant cannot wipe the compliance audit trail.
    # Recreate without ondelete → DB default RESTRICT / NO ACTION.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    fk_names = _tenant_fk_names(inspector)

    with op.batch_alter_table("audit_events") as batch_op:
        for name in fk_names:
            batch_op.drop_constraint(name, type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_audit_events_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("audit_events") as batch_op:
        batch_op.drop_constraint("fk_audit_events_tenant_id", type_="foreignkey")
        batch_op.create_foreign_key(
            "fk_audit_events_tenant_id",
            "tenants",
            ["tenant_id"],
            ["id"],
            ondelete="CASCADE",
        )
