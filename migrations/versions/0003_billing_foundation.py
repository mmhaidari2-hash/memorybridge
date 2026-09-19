"""Billing plans, subscriptions, and usage counters.

Revision ID: 0003_billing_foundation
Revises: 0002_commercial_foundation
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0003_billing_foundation"
down_revision = "0002_commercial_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("monthly_price_cents", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False),
        sa.Column("monthly_ops_limit", sa.Integer(), nullable=False),
        sa.Column("max_memories", sa.Integer(), nullable=False),
        sa.Column("stripe_price_id", sa.String(length=120), nullable=True),
        sa.Column("is_public", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_plans_code", "plans", ["code"], unique=True)

    op.create_table(
        "tenant_subscriptions",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("plan_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("stripe_customer_id", sa.String(length=120), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=120), nullable=True),
        sa.Column("current_period_start", sa.DateTime(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"]),
    )
    op.create_index("ix_tenant_subscriptions_tenant_id", "tenant_subscriptions", ["tenant_id"], unique=True)
    op.create_index("ix_tenant_subscriptions_plan_id", "tenant_subscriptions", ["plan_id"])
    op.create_index("ix_tenant_subscriptions_stripe_customer_id", "tenant_subscriptions", ["stripe_customer_id"])
    op.create_index(
        "ix_tenant_subscriptions_stripe_subscription_id",
        "tenant_subscriptions",
        ["stripe_subscription_id"],
    )

    op.create_table(
        "usage_counters",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("tenant_id", sa.String(), nullable=False),
        sa.Column("period_key", sa.String(length=7), nullable=False),
        sa.Column("ops_count", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("tenant_id", "period_key", name="uq_usage_tenant_period"),
    )
    op.create_index("ix_usage_counters_tenant_id", "usage_counters", ["tenant_id"])
    op.create_index("ix_usage_counters_period_key", "usage_counters", ["period_key"])


def downgrade() -> None:
    op.drop_index("ix_usage_counters_period_key", table_name="usage_counters")
    op.drop_index("ix_usage_counters_tenant_id", table_name="usage_counters")
    op.drop_table("usage_counters")

    op.drop_index("ix_tenant_subscriptions_stripe_subscription_id", table_name="tenant_subscriptions")
    op.drop_index("ix_tenant_subscriptions_stripe_customer_id", table_name="tenant_subscriptions")
    op.drop_index("ix_tenant_subscriptions_plan_id", table_name="tenant_subscriptions")
    op.drop_index("ix_tenant_subscriptions_tenant_id", table_name="tenant_subscriptions")
    op.drop_table("tenant_subscriptions")

    op.drop_index("ix_plans_code", table_name="plans")
    op.drop_table("plans")
