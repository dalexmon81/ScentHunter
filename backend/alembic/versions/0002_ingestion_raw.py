"""Add raw ingestion staging and link offers to their source row."""
from alembic import op
import sqlalchemy as sa

revision = "0002_ingestion_raw"
down_revision = "0001_initial_catalog"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_raw",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("external_product_id", sa.String(240)),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("product_variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="RESTRICT")),
        sa.Column("match_method", sa.String(60)),
        sa.Column("match_confidence", sa.Numeric(4, 3)),
        sa.Column("rejection_reason", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('pending','unmatched','matched','promoted','rejected')", name="ck_ingestion_raw_status"),
        sa.CheckConstraint("match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1)", name="ck_ingestion_raw_confidence_range"),
    )
    op.create_index("ix_ingestion_raw_store_status", "ingestion_raw", ["store_id", "status"])
    op.add_column("offers", sa.Column("ingestion_raw_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint("uq_offers_ingestion_raw_id", "offers", ["ingestion_raw_id"])
    op.create_foreign_key("fk_offers_ingestion_raw_id_ingestion_raw", "offers", "ingestion_raw", ["ingestion_raw_id"], ["id"], ondelete="RESTRICT")


def downgrade():
    op.drop_constraint("fk_offers_ingestion_raw_id_ingestion_raw", "offers", type_="foreignkey")
    op.drop_constraint("uq_offers_ingestion_raw_id", "offers", type_="unique")
    op.drop_column("offers", "ingestion_raw_id")
    op.drop_index("ix_ingestion_raw_store_status", table_name="ingestion_raw")
    op.drop_table("ingestion_raw")
