"""Persist retailer domain on store records."""
from alembic import op
import sqlalchemy as sa

revision = "0003_store_domain"
down_revision = "0002_ingestion_raw"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("stores", sa.Column("domain", sa.String(255), nullable=True))


def downgrade():
    op.drop_column("stores", "domain")
