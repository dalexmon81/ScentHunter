"""Add country-specific retailer shipping rates.

Revision ID: 0013_store_shipping_rates
Revises: 0012_store_authorizations
"""
from alembic import op
import sqlalchemy as sa

revision = "0013_store_shipping_rates"
down_revision = "0012_store_authorizations"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "store_shipping_rates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("postal_code_prefix", sa.String(length=24), nullable=True),
        sa.Column("currency", sa.String(length=3), server_default="EUR", nullable=False),
        sa.Column("base_cost", sa.Numeric(12, 2), nullable=True),
        sa.Column("free_shipping_threshold", sa.Numeric(12, 2), nullable=True),
        sa.Column("minimum_order_total", sa.Numeric(12, 2), nullable=True),
        sa.Column("maximum_order_total", sa.Numeric(12, 2), nullable=True),
        sa.Column("minimum_weight_kg", sa.Numeric(10, 3), nullable=True),
        sa.Column("maximum_weight_kg", sa.Numeric(10, 3), nullable=True),
        sa.Column("delivery_min_days", sa.Integer(), nullable=True),
        sa.Column("delivery_max_days", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="estimated", nullable=False),
        sa.Column("method", sa.String(length=24), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("evidence_reference", sa.String(length=240), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(country_code) = 2 AND country_code = upper(country_code)", name="shipping_country_iso2"),
        sa.CheckConstraint("currency = upper(currency) AND length(currency) = 3", name="shipping_currency_iso3"),
        sa.CheckConstraint("base_cost IS NULL OR base_cost >= 0", name="shipping_base_cost_nonnegative"),
        sa.CheckConstraint("free_shipping_threshold IS NULL OR free_shipping_threshold >= 0", name="shipping_free_threshold_nonnegative"),
        sa.CheckConstraint("minimum_order_total IS NULL OR minimum_order_total >= 0", name="shipping_min_order_nonnegative"),
        sa.CheckConstraint("maximum_order_total IS NULL OR maximum_order_total >= minimum_order_total", name="shipping_order_range_valid"),
        sa.CheckConstraint("minimum_weight_kg IS NULL OR minimum_weight_kg >= 0", name="shipping_min_weight_nonnegative"),
        sa.CheckConstraint("maximum_weight_kg IS NULL OR maximum_weight_kg >= minimum_weight_kg", name="shipping_weight_range_valid"),
        sa.CheckConstraint("delivery_min_days IS NULL OR delivery_min_days >= 0", name="shipping_delivery_min_nonnegative"),
        sa.CheckConstraint("delivery_max_days IS NULL OR delivery_max_days >= delivery_min_days", name="shipping_delivery_range_valid"),
        sa.CheckConstraint("status IN ('verified', 'estimated', 'unavailable')", name="shipping_rate_status"),
        sa.CheckConstraint("method IN ('official_page', 'api', 'feed', 'manual_confirmation')", name="shipping_rate_method"),
        sa.CheckConstraint("status <> 'verified' OR (base_cost IS NOT NULL AND valid_until IS NOT NULL)", name="verified_shipping_rate_has_cost_and_expiry"),
        sa.CheckConstraint("status <> 'verified' OR ((source_url IS NOT NULL AND length(trim(source_url)) > 0) OR (evidence_reference IS NOT NULL AND length(trim(evidence_reference)) > 0))", name="verified_shipping_rate_has_evidence"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_store_shipping_rates_destination", "store_shipping_rates", ["store_id", "country_code", "status"])


def downgrade():
    op.drop_index("ix_store_shipping_rates_destination", table_name="store_shipping_rates")
    op.drop_table("store_shipping_rates")
