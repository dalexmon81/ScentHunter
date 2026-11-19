"""Provision the authorized Notino France feed as a canonical store.

The Notino worker only schedules discovery for an active notino-fr row.
Without this seed, the connector exists in code but can never enter ingestion
on a fresh catalog database.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_seed_notino_store"
down_revision = "0005_connector_quarantine"
branch_labels = None
depends_on = None

_NOTINO_STORE_ID = "8c4e1b7a6d5f4092a1b3c7d9e0f24681"


def upgrade():
    op.execute(sa.text(
        """
        INSERT INTO stores (id, name, slug, domain, country, currency, status)
        VALUES (:id, :name, :slug, :domain, :country, :currency, :status)
        ON CONFLICT (slug) DO NOTHING
        """
    ).bindparams(
        id=_NOTINO_STORE_ID,
        name="Notino",
        slug="notino-fr",
        domain="notino.fr",
        country="FR",
        currency="EUR",
        status="active",
    ))


def downgrade():
    op.execute(sa.text("DELETE FROM stores WHERE slug = :slug").bindparams(
        slug="notino-fr"
    ))
