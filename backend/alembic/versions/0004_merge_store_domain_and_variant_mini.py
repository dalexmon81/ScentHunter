"""Merge independent store-domain and mini-packaging schema revisions.

Both revisions extend the Phase 2 ingestion schema and are required together.
"""
revision = "0004_merge_store_domain_and_variant_mini"
down_revision = ("0003_store_domain", "0003_variant_mini_packaging")
branch_labels = None
depends_on = None


def upgrade():
    # The parent revisions contain the actual schema changes.
    pass


def downgrade():
    # Keep the merged heads intact; downgrade the parent revisions explicitly.
    pass
