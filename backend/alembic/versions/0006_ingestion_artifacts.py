"""Persist immutable raw ingestion artifacts for replay.

Revision ID: 0006_ingestion_artifacts
Revises: 0005_canonical_identity_reviews
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_ingestion_artifacts"
down_revision = "0005_canonical_identity_reviews"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_artifacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("ingestion_run_id", sa.Uuid(), nullable=True),
        sa.Column("artifact_format", sa.String(length=24), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("raw_data", sa.LargeBinary(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ingestion_run_id"], ["ingestion_runs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("store_id", "sha256", name="uq_ingestion_artifacts_store_sha256"),
    )
    op.create_index(
        "ix_ingestion_artifacts_store_captured",
        "ingestion_artifacts",
        ["store_id", "captured_at"],
    )


def downgrade():
    op.drop_index("ix_ingestion_artifacts_store_captured", table_name="ingestion_artifacts")
    op.drop_table("ingestion_artifacts")
