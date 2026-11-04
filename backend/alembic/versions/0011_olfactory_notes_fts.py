"""Index structured olfactory notes for PostgreSQL full-text search.

Revision ID: 0011_olfactory_notes_fts
Revises: 0010_olfactory_notes
"""
from alembic import op

revision = "0011_olfactory_notes_fts"
down_revision = "0010_olfactory_notes"
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE INDEX ix_fragrances_olfactory_notes_fts ON fragrances "
        "USING GIN (to_tsvector('simple', coalesce(olfactory_notes::text, '')))"
    )


def downgrade():
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_fragrances_olfactory_notes_fts")
