"""Create normalized catalog, offers, history and audit tables."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_initial_catalog"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    op.create_table("brands", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(200), nullable=False), sa.Column("slug", sa.String(220), nullable=False, unique=True), sa.Column("normalized_name", sa.String(220), nullable=False, unique=True))
    op.create_table("fragrances", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("brand_id", sa.Uuid(), sa.ForeignKey("brands.id", ondelete="RESTRICT"), nullable=False), sa.Column("name", sa.String(240), nullable=False), sa.Column("slug", sa.String(260), nullable=False), sa.Column("gender", sa.String(40)), sa.Column("family", sa.String(100)), sa.Column("description", sa.Text()), sa.Column("image_url", sa.Text()), sa.UniqueConstraint("brand_id", "slug", name="uq_fragrances_brand_slug"))
    op.create_index("ix_fragrances_brand_id", "fragrances", ["brand_id"])
    op.create_index("ix_fragrances_name", "fragrances", ["name"])
    op.create_table("product_variants", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("fragrance_id", sa.Uuid(), sa.ForeignKey("fragrances.id", ondelete="RESTRICT"), nullable=False), sa.Column("concentration", sa.String(60)), sa.Column("size_ml", sa.Integer()), sa.Column("is_tester", sa.Boolean(), nullable=True), sa.Column("is_refill", sa.Boolean(), nullable=True), sa.Column("is_gift_set", sa.Boolean(), nullable=True), sa.Column("gtin", sa.String(14)), sa.Column("canonical_key", sa.String(320), nullable=False, unique=True), sa.CheckConstraint("size_ml IS NULL OR size_ml > 0", name="ck_product_variants_size_ml_positive"), sa.CheckConstraint("NOT (is_tester AND is_gift_set)", name="ck_product_variants_tester_not_gift_set"))
    op.create_index("ix_product_variants_fragrance_id", "product_variants", ["fragrance_id"])
    op.create_index("ix_product_variants_gtin", "product_variants", ["gtin"])
    op.create_index("ix_product_variants_size_ml", "product_variants", ["size_ml"])
    op.create_index("ix_product_variants_concentration", "product_variants", ["concentration"])
    op.create_table("stores", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("name", sa.String(160), nullable=False), sa.Column("slug", sa.String(180), nullable=False, unique=True), sa.Column("country", sa.String(2)), sa.Column("currency", sa.String(3), nullable=False, server_default="EUR"), sa.Column("status", sa.String(24), nullable=False, server_default="active"), sa.Column("reliability_score", sa.Numeric(4,3)), sa.Column("last_successful_sync_at", sa.DateTime(timezone=True)), sa.CheckConstraint("reliability_score IS NULL OR (reliability_score >= 0 AND reliability_score <= 1)", name="ck_stores_reliability_score_range"), sa.CheckConstraint("length(currency) = 3 AND currency = upper(currency)", name="ck_stores_currency_iso_code"))
    op.create_table("offers", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False), sa.Column("product_variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="RESTRICT")), sa.Column("external_product_id", sa.String(240)), sa.Column("url", sa.Text(), nullable=False), sa.Column("price", sa.Numeric(12,2), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("availability", sa.String(40)), sa.Column("shipping_cost", sa.Numeric(12,2)), sa.Column("source", sa.String(80), nullable=False), sa.Column("confidence", sa.Numeric(4,3)), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("valid_until", sa.DateTime(timezone=True)), sa.Column("status", sa.String(24), nullable=False, server_default="active"), sa.CheckConstraint("price >= 0", name="ck_offers_price_nonnegative"), sa.CheckConstraint("shipping_cost IS NULL OR shipping_cost >= 0", name="ck_offers_shipping_cost_nonnegative"), sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_offers_confidence_range"), sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_offers_currency_iso_code"))
    op.create_index("ix_offers_store_external_product", "offers", ["store_id","external_product_id"], unique=True, sqlite_where=sa.text("external_product_id IS NOT NULL"), postgresql_where=sa.text("external_product_id IS NOT NULL"))
    op.create_index("ix_offers_status", "offers", ["status"])
    op.create_index("ix_offers_store_id", "offers", ["store_id"])
    op.create_index("ix_offers_product_variant_id", "offers", ["product_variant_id"])
    op.create_index("ix_offers_captured_at", "offers", ["captured_at"])
    op.create_index("ix_offers_price", "offers", ["price"])
    op.create_table("price_history", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("offer_id", sa.Uuid(), sa.ForeignKey("offers.id", ondelete="CASCADE"), nullable=False), sa.Column("price", sa.Numeric(12,2), nullable=False), sa.Column("currency", sa.String(3), nullable=False), sa.Column("availability", sa.String(40)), sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.CheckConstraint("price >= 0", name="ck_price_history_price_nonnegative"), sa.CheckConstraint("currency ~ '^[A-Z]{3}$'", name="ck_price_history_currency_iso_code"))
    op.create_index("ix_price_history_offer_captured_at", "price_history", ["offer_id","captured_at"])
    op.create_table("match_audit", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("offer_id", sa.Uuid(), sa.ForeignKey("offers.id", ondelete="CASCADE"), nullable=False), sa.Column("product_variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="RESTRICT")), sa.Column("method", sa.String(60), nullable=False), sa.Column("confidence", sa.Numeric(4,3)), sa.Column("reason", sa.Text()), sa.Column("reviewed_by", sa.String(160)), sa.Column("reviewed_at", sa.DateTime(timezone=True)), sa.CheckConstraint("confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="ck_match_audit_confidence_range"))
    op.create_index("ix_match_audit_offer_id", "match_audit", ["offer_id"])
    op.create_table("ingestion_runs", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False), sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()), sa.Column("finished_at", sa.DateTime(timezone=True)), sa.Column("status", sa.String(24), nullable=False, server_default="queued"), sa.Column("products_discovered", sa.Integer(), nullable=False, server_default="0"), sa.Column("offers_created", sa.Integer(), nullable=False, server_default="0"), sa.Column("offers_updated", sa.Integer(), nullable=False, server_default="0"), sa.Column("offers_rejected", sa.Integer(), nullable=False, server_default="0"), sa.Column("errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'")), sa.CheckConstraint("products_discovered >= 0 AND offers_created >= 0 AND offers_updated >= 0 AND offers_rejected >= 0", name="ck_ingestion_runs_nonnegative_counters"))
    op.create_index("ix_ingestion_runs_store_started_at", "ingestion_runs", ["store_id","started_at"])

def downgrade():
    for table in ("ingestion_runs","match_audit","price_history","offers","stores","product_variants","fragrances","brands"):
        op.drop_table(table)
