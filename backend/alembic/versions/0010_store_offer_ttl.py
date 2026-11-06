"""Require an explicit per-store offer freshness TTL.

Revision ID: 0010_store_offer_ttl
Revises: 0009_live_ingestion_uniqueness
"""
from alembic import op
import sqlalchemy as sa

revision = "0010_store_offer_ttl"
down_revision = "0009_live_ingestion_uniqueness"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("stores") as batch_op:
        batch_op.add_column(sa.Column("offer_ttl_minutes", sa.Integer(), nullable=True))
        batch_op.create_check_constraint(
            "offer_ttl_positive",
            "offer_ttl_minutes IS NULL OR offer_ttl_minutes > 0",
        )


def downgrade():
    with op.batch_alter_table("stores") as batch_op:
        batch_op.drop_constraint("offer_ttl_positive", type_="check")
        batch_op.drop_column("offer_ttl_minutes")
