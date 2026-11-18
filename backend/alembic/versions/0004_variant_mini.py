"""Add explicit mini format to canonical product variants."""
from alembic import op
import sqlalchemy as sa

revision = "0004_variant_mini"
down_revision = "0003_store_domain"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("product_variants", sa.Column("is_mini", sa.Boolean(), nullable=True))


def downgrade():
    op.drop_column("product_variants", "is_mini")
