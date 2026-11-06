"""Preserve fractional millilitre sizes on canonical variants.

Revision ID: 0008_variant_size_precision
Revises: 0007_ingestion_dead_letters
"""
from alembic import op
import sqlalchemy as sa

revision = "0008_variant_size_precision"
down_revision = "0007_ingestion_dead_letters"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("product_variants") as batch_op:
        batch_op.alter_column(
            "size_ml",
            existing_type=sa.Integer(),
            type_=sa.Numeric(10, 4),
            existing_nullable=True,
            postgresql_using="size_ml::numeric(10,4)",
        )


def downgrade():
    with op.batch_alter_table("product_variants") as batch_op:
        batch_op.alter_column(
            "size_ml",
            existing_type=sa.Numeric(10, 4),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using="round(size_ml)::integer",
        )
