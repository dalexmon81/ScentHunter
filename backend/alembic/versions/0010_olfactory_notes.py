"""Add structured olfactory notes for catalog search.

Revision ID: 0010_olfactory_notes
Revises: 0009_catalog_search_fts
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_olfactory_notes"
down_revision = "0009_catalog_search_fts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("fragrances", sa.Column("olfactory_notes", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("fragrances", "olfactory_notes")
