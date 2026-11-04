"""Add PostgreSQL GIN indexes for canonical catalog full-text search.

Revision ID: 0009_catalog_search_fts
Revises: 0008_offer_lifecycle_states
"""
from alembic import op

revision = "0009_catalog_search_fts"
down_revision = "0008_offer_lifecycle_states"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    # Keep index expressions byte-for-byte aligned with the query expressions
    # in app.search.catalog_search. The simple configuration avoids language-
    # specific stemming across the supported European retailer catalogs.
    op.execute(
        "CREATE INDEX ix_brands_name_fts ON brands "
        "USING GIN (to_tsvector('simple', name))"
    )
    op.execute(
        "CREATE INDEX ix_fragrances_name_fts ON fragrances "
        "USING GIN (to_tsvector('simple', name))"
    )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_fragrances_name_fts")
    op.execute("DROP INDEX IF EXISTS ix_brands_name_fts")
