"""Add controlled product form classification to canonical variants."""
from alembic import op
import sqlalchemy as sa

revision = "0004_variant_product_form"
down_revision = "0003_store_domain"
branch_labels = None
depends_on = None

_PRODUCT_FORM_CHECK = (
    "product_form IS NULL OR product_form IN "
    "('fine_fragrance','perfume_oil','deodorant','body_mist','hair_mist',"
    "'body_care','home_fragrance','gift_set','discovery_set')"
)


def upgrade():
    # Batch mode keeps the migration compatible with SQLite and PostgreSQL.
    # NULL is intentional: legacy variants remain unclassified until evidence
    # supports a form; no product form is backfilled by inference.
    with op.batch_alter_table("product_variants") as batch:
        batch.add_column(sa.Column("product_form", sa.String(length=40), nullable=True))
        batch.create_check_constraint("product_form_allowed", _PRODUCT_FORM_CHECK)
    op.create_index(
        "ix_product_variants_product_form",
        "product_variants",
        ["product_form"],
    )


def downgrade():
    op.drop_index("ix_product_variants_product_form", table_name="product_variants")
    with op.batch_alter_table("product_variants") as batch:
        batch.drop_constraint("product_form_allowed", type_="check")
        batch.drop_column("product_form")
