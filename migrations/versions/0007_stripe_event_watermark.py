"""Add last_stripe_event_ts for out-of-order webhook protection.

Revision ID: 0007_stripe_event_watermark
Revises: 0006_stripe_webhook_events
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_stripe_event_watermark"
down_revision = "0006_stripe_webhook_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tenant_subscriptions") as batch_op:
        batch_op.add_column(
            sa.Column("last_stripe_event_ts", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.alter_column("last_stripe_event_ts", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("tenant_subscriptions") as batch_op:
        batch_op.drop_column("last_stripe_event_ts")
