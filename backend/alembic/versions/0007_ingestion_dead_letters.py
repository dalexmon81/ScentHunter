"""Persist Celery tasks that exhaust retries.

Revision ID: 0007_ingestion_dead_letters
Revises: 0006_ingestion_artifacts
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_ingestion_dead_letters"
down_revision = "0006_ingestion_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_dead_letters",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_name", sa.String(length=240), nullable=False),
        sa.Column("task_id", sa.String(length=80), nullable=False),
        sa.Column("args_repr", sa.Text(), nullable=False),
        sa.Column("kwargs_repr", sa.Text(), nullable=False),
        sa.Column("error", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="open", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by", sa.String(length=160), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_ingestion_dead_letters_task_id"),
    )
    op.create_index(
        "ix_ingestion_dead_letters_status_created",
        "ingestion_dead_letters",
        ["status", "created_at"],
    )


def downgrade():
    op.drop_index("ix_ingestion_dead_letters_status_created", table_name="ingestion_dead_letters")
    op.drop_table("ingestion_dead_letters")
