"""Persist the isolated Notino CJ retailer listing snapshot."""
from alembic import op
import sqlalchemy as sa

revision = "0004_notino_feed_listings"
down_revision = "0003_store_domain"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notino_feed_listings",
        sa.Column("external_id", sa.String(length=240), primary_key=True),
        sa.Column("brand", sa.String(length=240), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("gtin", sa.String(length=32), nullable=True),
        sa.Column("size_ml", sa.Float(), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("availability", sa.String(length=40), nullable=False),
        sa.Column("affiliate_url", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("source_last_updated", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("price > 0", name="ck_notino_feed_listings_price_positive"),
        sa.CheckConstraint("currency = 'EUR'", name="ck_notino_feed_listings_currency_eur"),
        sa.CheckConstraint("availability IN ('in stock', 'out of stock')", name="ck_notino_feed_listings_availability"),
    )
    op.create_index("ix_notino_feed_listings_brand_title", "notino_feed_listings", ["brand", "title"])


def downgrade():
    op.drop_index("ix_notino_feed_listings_brand_title", table_name="notino_feed_listings")
    op.drop_table("notino_feed_listings")
