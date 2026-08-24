"""add billing state and webhook events

Revision ID: 0005_billing_state
Revises: 0004_usage_events
"""

from alembic import op
import sqlalchemy as sa

revision = "0005_billing_state"
down_revision = "0004_usage_events"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("tenants", sa.Column("stripe_customer_id", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("stripe_subscription_id", sa.String(), nullable=True))
    op.add_column("tenants", sa.Column("subscription_status", sa.String(), nullable=True))
    op.create_index("ix_tenants_stripe_customer_id", "tenants", ["stripe_customer_id"], unique=True)
    op.create_index("ix_tenants_stripe_subscription_id", "tenants", ["stripe_subscription_id"], unique=True)

    op.create_table(
        "billing_events",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("provider_event_id", sa.String(), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("processed_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider_event_id", name="uq_billing_events_provider_event_id"),
    )
    op.create_index("ix_billing_events_tenant_id", "billing_events", ["tenant_id"])
    op.create_index("ix_billing_events_provider_event_id", "billing_events", ["provider_event_id"], unique=True)
    op.create_index("ix_billing_events_event_type", "billing_events", ["event_type"])


def downgrade():
    op.drop_index("ix_billing_events_event_type", table_name="billing_events")
    op.drop_index("ix_billing_events_provider_event_id", table_name="billing_events")
    op.drop_index("ix_billing_events_tenant_id", table_name="billing_events")
    op.drop_table("billing_events")
    op.drop_index("ix_tenants_stripe_subscription_id", table_name="tenants")
    op.drop_index("ix_tenants_stripe_customer_id", table_name="tenants")
    op.drop_column("tenants", "subscription_status")
    op.drop_column("tenants", "stripe_subscription_id")
    op.drop_column("tenants", "stripe_customer_id")
