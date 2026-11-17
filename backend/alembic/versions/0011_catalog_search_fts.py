"""Add PostgreSQL full-text indexes for canonical brand and fragrance names.

Revision ID: 0011_catalog_search_fts
Revises: 0010_store_offer_ttl
"""
from alembic import op

revision = "0011_catalog_search_fts"
down_revision = "0010_store_offer_ttl"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_brands_name_fts "
        "ON brands USING GIN (to_tsvector('simple', name))"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_fragrances_name_fts "
        "ON fragrances USING GIN (to_tsvector('simple', name))"
    )


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_fragrances_name_fts")
    op.execute("DROP INDEX IF EXISTS ix_brands_name_fts")
