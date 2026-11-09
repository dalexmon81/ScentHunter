"""Add revocable opaque account sessions.

Revision ID: 0015_user_sessions
Revises: 0014_user_accounts_destinations
"""
from alembic import op
import sqlalchemy as sa

revision = "0015_user_sessions"
down_revision = "0014_user_accounts_destinations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_user_sessions_token_hash"),
    )
    op.create_index("ix_user_sessions_user_expiry", "user_sessions", ["user_id", "expires_at"])
    op.create_index("ix_user_sessions_expiry", "user_sessions", ["expires_at"])


def downgrade():
    op.drop_index("ix_user_sessions_expiry", table_name="user_sessions")
    op.drop_index("ix_user_sessions_user_expiry", table_name="user_sessions")
    op.drop_table("user_sessions")
