"""Track consecutive connector failures and explicit quarantine state."""
from alembic import op
import sqlalchemy as sa

revision = "0005_connector_quarantine"
down_revision = "0004_variant_mini"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stores", sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("stores", sa.Column("last_connector_error", sa.Text(), nullable=True))
    op.add_column("stores", sa.Column("quarantined_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column("stores", "quarantined_at")
    op.drop_column("stores", "last_connector_error")
    op.drop_column("stores", "consecutive_failures")
