"""Record processed Stripe webhook event IDs for replay protection.

Revision ID: 0006_stripe_webhook_events
Revises: 0005_tenant_soft_delete
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_stripe_webhook_events"
down_revision = "0005_tenant_soft_delete"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stripe_webhook_events_event_type", "stripe_webhook_events", ["event_type"])


def downgrade() -> None:
    op.drop_index("ix_stripe_webhook_events_event_type", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")
