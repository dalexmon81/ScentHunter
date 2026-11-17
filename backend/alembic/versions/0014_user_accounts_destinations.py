"""Add account profiles and saved delivery destinations.

Revision ID: 0014_user_accounts_destinations
Revises: 0013_store_shipping_rates
"""
from alembic import op
import sqlalchemy as sa

revision = "0014_user_accounts_destinations"
down_revision = "0013_store_shipping_rates"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user_accounts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("residence_country_code", sa.String(length=2), nullable=False),
        sa.Column("residence_postal_code", sa.String(length=24), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("email = lower(trim(email)) AND length(email) > 3", name="user_account_email_normalized"),
        sa.CheckConstraint("length(residence_country_code) = 2 AND residence_country_code = upper(residence_country_code)", name="user_account_residence_country_iso2"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email", name="uq_user_accounts_email"),
    )
    op.create_table(
        "user_delivery_destinations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=False),
        sa.Column("postal_code", sa.String(length=24), nullable=True),
        sa.Column("is_default", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(country_code) = 2 AND country_code = upper(country_code)", name="delivery_destination_country_iso2"),
        sa.ForeignKeyConstraint(["user_id"], ["user_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_delivery_destinations_user", "user_delivery_destinations", ["user_id"])
    op.create_index(
        "uq_user_delivery_destinations_one_default",
        "user_delivery_destinations", ["user_id"], unique=True,
        postgresql_where=sa.text("is_default = true"),
        sqlite_where=sa.text("is_default = 1"),
    )


def downgrade():
    op.drop_index("uq_user_delivery_destinations_one_default", table_name="user_delivery_destinations")
    op.drop_index("ix_user_delivery_destinations_user", table_name="user_delivery_destinations")
    op.drop_table("user_delivery_destinations")
    op.drop_table("user_accounts")
