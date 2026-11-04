"""Add explicit mini packaging metadata to product variants.

The field is nullable so existing catalog rows remain unknown rather than being
incorrectly classified as standard or mini products.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_variant_mini_packaging"
down_revision = "0002_ingestion_raw"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "product_variants",
        sa.Column("is_mini", sa.Boolean(), nullable=True),
    )


def downgrade():
    op.drop_column("product_variants", "is_mini")
