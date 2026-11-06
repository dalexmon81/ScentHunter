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
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot ALTER COLUMN TYPE; force Alembic's table-copy strategy.
        with op.batch_alter_table("product_variants", recreate="always") as batch_op:
            batch_op.alter_column(
                "size_ml",
                existing_type=sa.Integer(),
                type_=sa.Numeric(10, 4),
                existing_nullable=True,
            )
    else:
        op.alter_column(
            "product_variants",
            "size_ml",
            existing_type=sa.Integer(),
            type_=sa.Numeric(10, 4),
            existing_nullable=True,
            postgresql_using="size_ml::numeric(10,4)",
        )


def downgrade():
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("product_variants", recreate="always") as batch_op:
            batch_op.alter_column(
                "size_ml",
                existing_type=sa.Numeric(10, 4),
                type_=sa.Integer(),
                existing_nullable=True,
            )
    else:
        op.alter_column(
            "product_variants",
            "size_ml",
            existing_type=sa.Numeric(10, 4),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using="round(size_ml)::integer",
        )
