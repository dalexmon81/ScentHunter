"""Add raw ingestion staging, legacy ID maps and offer source linkage."""
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
        sa.Column("legacy_product_id", sa.String(80)),
        sa.Column("legacy_variant_id", sa.String(100)),
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
    op.create_table(
        "legacy_product_id_map",
        sa.Column("legacy_product_id", sa.String(80), primary_key=True),
        sa.Column("fragrance_id", sa.Uuid(), sa.ForeignKey("fragrances.id", ondelete="RESTRICT"), nullable=False, unique=True),
    )
    op.create_table(
        "legacy_variant_id_map",
        sa.Column("legacy_variant_id", sa.String(100), primary_key=True),
        sa.Column("product_variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="RESTRICT"), nullable=False, unique=True),
    )
    with op.batch_alter_table("offers") as batch:
        batch.add_column(sa.Column("ingestion_raw_id", sa.Uuid(), nullable=True))
        batch.create_unique_constraint("uq_offers_ingestion_raw_id", ["ingestion_raw_id"])
        batch.create_foreign_key(
            "fk_offers_ingestion_raw_id_ingestion_raw", "ingestion_raw",
            ["ingestion_raw_id"], ["id"], ondelete="RESTRICT"
        )


def downgrade():
    with op.batch_alter_table("offers") as batch:
        batch.drop_constraint("fk_offers_ingestion_raw_id_ingestion_raw", type_="foreignkey")
        batch.drop_constraint("uq_offers_ingestion_raw_id", type_="unique")
        batch.drop_column("ingestion_raw_id")
    op.drop_table("legacy_variant_id_map")
    op.drop_table("legacy_product_id_map")
    op.drop_index("ix_ingestion_raw_store_status", table_name="ingestion_raw")
    op.drop_table("ingestion_raw")
