"""Create durable queue for canonical identity conflicts."""
from alembic import op
import sqlalchemy as sa

revision = "0005_canonical_identity_reviews"
down_revision = "0004_merge_store_domain_and_variant_mini"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "canonical_identity_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("canonical_key", sa.String(length=320), nullable=False),
        sa.Column("normalized_payload", sa.JSON(), nullable=False),
        sa.Column("supplied_gtin", sa.String(length=14), nullable=True),
        sa.Column("reason", sa.String(length=160), nullable=False),
        sa.Column("source_reference", sa.String(length=240), nullable=True),
        sa.Column("status", sa.String(length=24), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by", sa.String(length=160), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'duplicate')",
            name="canonical_identity_review_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fingerprint"),
    )
    op.create_index(
        "ix_canonical_identity_reviews_status_created",
        "canonical_identity_reviews",
        ["status", "created_at"],
    )
    op.create_index(
        "ix_canonical_identity_reviews_canonical_key",
        "canonical_identity_reviews",
        ["canonical_key"],
    )


def downgrade():
    op.drop_index("ix_canonical_identity_reviews_canonical_key", table_name="canonical_identity_reviews")
    op.drop_index("ix_canonical_identity_reviews_status_created", table_name="canonical_identity_reviews")
    op.drop_table("canonical_identity_reviews")
