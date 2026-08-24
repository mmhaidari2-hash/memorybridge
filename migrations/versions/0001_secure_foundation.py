"""Initial secure foundation schema.

Revision ID: 0001_secure_foundation
Revises:
Create Date: 2026-08-24
"""

from alembic import op
import sqlalchemy as sa

revision = "0001_secure_foundation"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("user_token_hash", sa.String(length=64), nullable=False),
        sa.Column("full_name", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_users_user_token_hash", "users", ["user_token_hash"], unique=True)

    op.create_table(
        "memory_records",
        sa.Column("id", sa.String(), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(), nullable=False),
        sa.Column("session_token_hash", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(), nullable=True),
        sa.Column("encrypted_content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_memory_records_user_id", "memory_records", ["user_id"], unique=False)
    op.create_index(
        "ix_memory_records_session_token_hash",
        "memory_records",
        ["session_token_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_memory_records_session_token_hash", table_name="memory_records")
    op.drop_index("ix_memory_records_user_id", table_name="memory_records")
    op.drop_table("memory_records")
    op.drop_index("ix_users_user_token_hash", table_name="users")
    op.drop_table("users")
