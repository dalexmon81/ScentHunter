"""Add namespaced identifiers for canonical product variants.

Revision ID: 0016_product_identifiers
Revises: 0015_user_sessions
"""
from alembic import op
import sqlalchemy as sa

revision = "0016_product_identifiers"
down_revision = "0015_user_sessions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "product_identifiers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("product_variant_id", sa.Uuid(), nullable=False),
        sa.Column("identifier_type", sa.String(length=16), nullable=False),
        sa.Column("namespace", sa.String(length=180), nullable=False),
        sa.Column("value", sa.String(length=240), nullable=False),
        sa.Column("normalized_value", sa.String(length=240), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("identifier_type IN ('gtin', 'mpn', 'sku')", name="product_identifier_type"),
        sa.ForeignKeyConstraint(["product_variant_id"], ["product_variants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("identifier_type", "namespace", "normalized_value", name="uq_product_identifier_namespace_value"),
    )
    op.create_index("ix_product_identifiers_variant", "product_identifiers", ["product_variant_id"])
    op.create_index("ix_product_identifiers_store", "product_identifiers", ["store_id"])


def downgrade():
    op.drop_index("ix_product_identifiers_store", table_name="product_identifiers")
    op.drop_index("ix_product_identifiers_variant", table_name="product_identifiers")
    op.drop_table("product_identifiers")
