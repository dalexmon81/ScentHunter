"""Add durable PostgreSQL-backed ingestion job queue."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006_postgres_ingestion_queue"
down_revision = "0005_connector_quarantine"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ingestion_queue_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("stage", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("dedupe_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("worker_id", sa.String(200)),
        sa.Column("last_error", sa.Text()),
        sa.CheckConstraint("stage IN ('discover','fetch','refresh')", name="stage"),
        sa.CheckConstraint("status IN ('queued','running','completed','failed')", name="status"),
        sa.CheckConstraint("attempts >= 0 AND max_attempts > 0", name="attempts"),
    )
    op.create_index(
        "uq_ingestion_queue_active_dedupe",
        "ingestion_queue_jobs",
        ["stage", "dedupe_key"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued','running')"),
    )
    op.create_index(
        "ix_ingestion_queue_ready",
        "ingestion_queue_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_ingestion_queue_stale",
        "ingestion_queue_jobs",
        ["status", "started_at"],
    )


def downgrade():
    op.drop_index("ix_ingestion_queue_stale", table_name="ingestion_queue_jobs")
    op.drop_index("ix_ingestion_queue_ready", table_name="ingestion_queue_jobs")
    op.drop_index("uq_ingestion_queue_active_dedupe", table_name="ingestion_queue_jobs")
    op.drop_table("ingestion_queue_jobs")
