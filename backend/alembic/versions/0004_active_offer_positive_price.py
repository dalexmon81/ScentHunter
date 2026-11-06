"""Require strictly positive prices on active offers.

Historical/rejected offers may retain zero values for diagnostics, but an
active offer must represent a purchasable item with a positive price.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_active_offer_positive_price"
down_revision = "0003_store_domain"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("offers") as batch:
        batch.create_check_constraint(
            "active_offer_positive_price",
            "status <> 'active' OR price > 0",
        )


def downgrade():
    with op.batch_alter_table("offers") as batch:
        batch.drop_constraint("active_offer_positive_price", type_="check")
