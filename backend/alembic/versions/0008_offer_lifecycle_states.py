"""Add independent validation and publication lifecycle columns.

Revision ID: 0008_offer_lifecycle_states
Revises: 0007_ingestion_dead_letters
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_offer_lifecycle_states"
down_revision = "0007_ingestion_dead_letters"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "ingestion_raw",
        sa.Column("validation_status", sa.String(length=24),
                  nullable=False, server_default="pending"),
    )
    op.create_check_constraint(
        "ingestion_raw_validation_status",
        "ingestion_raw",
        "validation_status IN ('pending','validated','rejected')",
    )
    op.add_column(
        "offers",
        sa.Column("publication_status", sa.String(length=24),
                  nullable=False, server_default="draft"),
    )
    op.create_check_constraint(
        "offers_publication_status",
        "offers",
        "publication_status IN ('draft','published','stale','rejected','quarantined')",
    )
    # Existing offers remain legacy-active for current readers but are draft
    # in the new lifecycle until their evidence is explicitly revalidated.
    op.create_index(
        "ix_offers_publication_status",
        "offers",
        ["publication_status"],
    )


def downgrade():
    op.drop_index("ix_offers_publication_status", table_name="offers")
    op.drop_constraint("offers_publication_status", "offers", type_="check")
    op.drop_column("offers", "publication_status")
    op.drop_constraint("ingestion_raw_validation_status", "ingestion_raw", type_="check")
    op.drop_column("ingestion_raw", "validation_status")
