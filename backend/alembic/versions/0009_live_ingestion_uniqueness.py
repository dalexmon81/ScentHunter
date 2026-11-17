"""Prevent concurrent duplicate live ingestion rows per store product.

Revision ID: 0009_live_ingestion_uniqueness
Revises: 0008_variant_size_precision
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_live_ingestion_uniqueness"
down_revision = "0008_variant_size_precision"
branch_labels = None
depends_on = None

PREDICATE = "external_product_id IS NOT NULL AND status IN ('pending','unmatched','matched')"


def upgrade():
    op.create_index(
        "uq_ingestion_raw_live_store_external",
        "ingestion_raw",
        ["store_id", "external_product_id"],
        unique=True,
        sqlite_where=sa.text(PREDICATE),
        postgresql_where=sa.text(PREDICATE),
    )


def downgrade():
    op.drop_index("uq_ingestion_raw_live_store_external", table_name="ingestion_raw")
