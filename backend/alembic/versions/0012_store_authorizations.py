"""Add auditable, fail-closed retailer authorization records.

Revision ID: 0012_store_authorizations
Revises: 0011_catalog_search_fts
"""
from alembic import op
import sqlalchemy as sa

revision = "0012_store_authorizations"
down_revision = "0011_catalog_search_fts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "store_authorizations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("store_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("collection_method", sa.String(length=24), nullable=False),
        sa.Column("scopes", sa.JSON(), nullable=False),
        sa.Column("authorization_reference", sa.String(length=240), nullable=True),
        sa.Column("evidence_url", sa.Text(), nullable=True),
        sa.Column("approved_by", sa.String(length=160), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'revoked', 'expired')", name="store_authorization_status"),
        sa.CheckConstraint("collection_method IN ('api', 'feed', 'affiliate_feed', 'manual_url', 'other')", name="store_authorization_method"),
        sa.ForeignKeyConstraint(["store_id"], ["stores.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_store_authorizations_store_status", "store_authorizations", ["store_id", "status"])


def downgrade():
    op.drop_index("ix_store_authorizations_store_status", table_name="store_authorizations")
    op.drop_table("store_authorizations")
