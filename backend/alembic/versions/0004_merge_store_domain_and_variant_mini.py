"""Merge independent store-domain and mini-packaging schema revisions.

Both revisions extend the Phase 2 ingestion schema and are required together.
"""
revision = "0004_merge_store_domain_and_variant_mini"
down_revision = ("0003_store_domain", "0003_variant_mini_packaging")
branch_labels = None
depends_on = None


def upgrade():
    # Alembic defaults version_num to VARCHAR(32), but this merged revision
    # identifier is longer. Widen existing PostgreSQL databases before Alembic
    # writes the new revision; SQLite does not enforce VARCHAR lengths.
    from alembic import op

    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE alembic_version "
            "ALTER COLUMN version_num TYPE VARCHAR(128)"
        )


def downgrade():
    # Keep the merged heads intact; downgrade the parent revisions explicitly.
    pass
