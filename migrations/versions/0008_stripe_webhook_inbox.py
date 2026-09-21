"""Durable Stripe webhook inbox for crash-safe acceptance.

Revision ID: 0008_stripe_webhook_inbox
Revises: 0007_stripe_event_watermark
Create Date: 2026-09-21
"""

from alembic import op
import sqlalchemy as sa

revision = "0008_stripe_webhook_inbox"
down_revision = "0007_stripe_event_watermark"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stripe_webhook_inbox",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_stripe_webhook_inbox_event_type", "stripe_webhook_inbox", ["event_type"])
    op.create_index("ix_stripe_webhook_inbox_status", "stripe_webhook_inbox", ["status"])


def downgrade() -> None:
    op.drop_index("ix_stripe_webhook_inbox_status", table_name="stripe_webhook_inbox")
    op.drop_index("ix_stripe_webhook_inbox_event_type", table_name="stripe_webhook_inbox")
    op.drop_table("stripe_webhook_inbox")
