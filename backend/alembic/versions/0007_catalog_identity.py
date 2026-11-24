"""Add stable retailer products, catalog aliases, GTIN evidence and stage runs."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "0007_catalog_identity"
down_revision = "0006_postgres_ingestion_queue"
branch_labels = None
depends_on = None


def _as_uuid(value):
    if value is None or isinstance(value, uuid.UUID):
        return value
    return uuid.UUID(str(value))


def _payload_dict(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _first_text(payload, keys):
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _min_time(current, candidate):
    if candidate is None:
        return current
    if current is None or candidate < current:
        return candidate
    return current


def _max_time(current, candidate):
    if candidate is None:
        return current
    if current is None or candidate > current:
        return candidate
    return current


def _backfill_store_products(connection):
    """Build stable retailer identities from existing raw rows and current offers.

    The migration intentionally does not infer a canonical variant from raw
    payloads. Only an existing current offer may provide that mapping.
    """
    metadata = sa.MetaData()
    raw = sa.Table("ingestion_raw", metadata, autoload_with=connection)
    offers = sa.Table("offers", metadata, autoload_with=connection)
    products = sa.table(
        "store_products",
        sa.column("id", sa.Uuid()),
        sa.column("store_id", sa.Uuid()),
        sa.column("external_product_id", sa.String(240)),
        sa.column("canonical_url", sa.Text()),
        sa.column("raw_title", sa.Text()),
        sa.column("product_variant_id", sa.Uuid()),
        sa.column("status", sa.String(24)),
        sa.column("first_seen_at", sa.DateTime(timezone=True)),
        sa.column("last_seen_at", sa.DateTime(timezone=True)),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    offers_update = sa.table(
        "offers",
        sa.column("store_id", sa.Uuid()),
        sa.column("external_product_id", sa.String(240)),
        sa.column("store_product_id", sa.Uuid()),
    )
    raw_update = sa.table(
        "ingestion_raw",
        sa.column("store_id", sa.Uuid()),
        sa.column("external_product_id", sa.String(240)),
        sa.column("store_product_id", sa.Uuid()),
    )

    grouped = {}
    raw_rows = connection.execute(
        sa.select(
            raw.c.store_id,
            raw.c.external_product_id,
            raw.c.raw_payload,
            raw.c.created_at,
            raw.c.updated_at,
        ).where(raw.c.external_product_id.is_not(None))
    ).mappings()

    for row in raw_rows:
        store_id = _as_uuid(row["store_id"])
        external_id = str(row["external_product_id"]).strip()
        if not external_id:
            continue
        key = (store_id, external_id)
        item = grouped.setdefault(key, {
            "id": uuid.uuid4(),
            "store_id": store_id,
            "external_product_id": external_id,
            "canonical_url": None,
            "raw_title": None,
            "product_variant_id": None,
            "status": "discovered",
            "first_seen_at": None,
            "last_seen_at": None,
            "created_at": row["created_at"] or datetime.now(timezone.utc),
            "updated_at": row["updated_at"] or datetime.now(timezone.utc),
        })
        payload = _payload_dict(row["raw_payload"])
        item["canonical_url"] = item["canonical_url"] or _first_text(
            payload, ("product_url",)
        )
        item["raw_title"] = item["raw_title"] or _first_text(
            payload, ("title", "name", "raw_name")
        )
        item["first_seen_at"] = _min_time(item["first_seen_at"], row["created_at"])
        item["last_seen_at"] = _max_time(item["last_seen_at"], row["updated_at"])
        item["created_at"] = _min_time(item["created_at"], row["created_at"])
        item["updated_at"] = _max_time(item["updated_at"], row["updated_at"])

    offer_rows = connection.execute(
        sa.select(
            offers.c.store_id,
            offers.c.external_product_id,
            offers.c.url,
            offers.c.product_variant_id,
            offers.c.status,
            offers.c.captured_at,
        ).where(offers.c.external_product_id.is_not(None))
    ).mappings()

    for row in offer_rows:
        store_id = _as_uuid(row["store_id"])
        external_id = str(row["external_product_id"]).strip()
        if not external_id:
            continue
        key = (store_id, external_id)
        item = grouped.setdefault(key, {
            "id": uuid.uuid4(),
            "store_id": store_id,
            "external_product_id": external_id,
            "canonical_url": None,
            "raw_title": None,
            "product_variant_id": None,
            "status": "discovered",
            "first_seen_at": None,
            "last_seen_at": None,
            "created_at": row["captured_at"] or datetime.now(timezone.utc),
            "updated_at": row["captured_at"] or datetime.now(timezone.utc),
        })
        if row["product_variant_id"] is not None:
            item["product_variant_id"] = _as_uuid(row["product_variant_id"])
        if str(row["status"] or "").lower() == "active":
            item["status"] = "active"
        item["first_seen_at"] = _min_time(item["first_seen_at"], row["captured_at"])
        item["last_seen_at"] = _max_time(item["last_seen_at"], row["captured_at"])
        item["created_at"] = _min_time(item["created_at"], row["captured_at"])
        item["updated_at"] = _max_time(item["updated_at"], row["captured_at"])

    now = datetime.now(timezone.utc)
    for item in grouped.values():
        item["first_seen_at"] = item["first_seen_at"] or item["created_at"] or now
        item["last_seen_at"] = item["last_seen_at"] or item["updated_at"] or now
        item["created_at"] = item["created_at"] or now
        item["updated_at"] = item["updated_at"] or now

    values = list(grouped.values())
    for offset in range(0, len(values), 500):
        connection.execute(products.insert(), values[offset:offset + 500])

    # Correlated subqueries are supported by both PostgreSQL and SQLite.
    connection.execute(
        sa.update(offers_update)
        .where(offers_update.c.external_product_id.is_not(None))
        .values(store_product_id=sa.select(products.c.id).where(
            products.c.store_id == offers_update.c.store_id,
            products.c.external_product_id == offers_update.c.external_product_id,
        ).scalar_subquery())
    )
    connection.execute(
        sa.update(raw_update)
        .where(raw_update.c.external_product_id.is_not(None))
        .values(store_product_id=sa.select(products.c.id).where(
            products.c.store_id == raw_update.c.store_id,
            products.c.external_product_id == raw_update.c.external_product_id,
        ).scalar_subquery())
    )

    unlinked_offers = connection.execute(
        sa.select(sa.func.count()).select_from(offers).where(
            offers.c.external_product_id.is_not(None),
            offers.c.store_product_id.is_(None),
        )
    ).scalar_one()
    unlinked_raw = connection.execute(
        sa.select(sa.func.count()).select_from(raw).where(
            raw.c.external_product_id.is_not(None),
            raw.c.store_product_id.is_(None),
        )
    ).scalar_one()
    if unlinked_offers or unlinked_raw:
        raise RuntimeError(
            "Phase 2 store-product backfill left external IDs unlinked: "
            f"offers={unlinked_offers}, ingestion_raw={unlinked_raw}"
        )

def _backfill_legacy_gtins(connection):
    variants = sa.Table(
        "product_variants", sa.MetaData(), autoload_with=connection
    )
    gtins = sa.table(
        "product_variant_gtins",
        sa.column("id", sa.Uuid()),
        sa.column("product_variant_id", sa.Uuid()),
        sa.column("gtin", sa.String(14)),
        sa.column("normalized_gtin", sa.String(14)),
        sa.column("market", sa.String(2)),
        sa.column("source", sa.String(80)),
        sa.column("verification_status", sa.String(24)),
        sa.column("is_primary", sa.Boolean()),
        sa.column("evidence", sa.JSON()),
        sa.column("observed_at", sa.DateTime(timezone=True)),
        sa.column("verified_at", sa.DateTime(timezone=True)),
    )
    allowed_lengths = {8, 12, 13, 14}
    rows = connection.execute(
        sa.select(variants.c.id, variants.c.gtin).where(
            variants.c.gtin.is_not(None)
        )
    ).all()
    values = []
    for variant_id, raw_gtin in rows:
        original = str(raw_gtin).strip()
        if any(char not in "0123456789 -" for char in original):
            continue
        normalized = "".join(char for char in original if char in "0123456789")
        if len(normalized) not in allowed_lengths:
            # Preserve the original legacy column; do not promote malformed
            # values into the searchable GTIN evidence table.
            continue
        body = normalized[:-1]
        weighted_sum = sum(
            int(digit) * (3 if (len(body) - 1 - index) % 2 == 0 else 1)
            for index, digit in enumerate(body)
        )
        expected_check_digit = (10 - (weighted_sum % 10)) % 10
        if expected_check_digit != int(normalized[-1]):
            continue
        values.append({
            "id": uuid.uuid4(),
            "product_variant_id": _as_uuid(variant_id),
            "gtin": original,
            "normalized_gtin": normalized,
            "source": "legacy_product_variants.gtin",
            "verification_status": "legacy",
            "is_primary": True,
            "observed_at": datetime.now(timezone.utc),
        })
    for offset in range(0, len(values), 500):
        connection.execute(gtins.insert(), values[offset:offset + 500])

def upgrade():
    op.create_table(
        "store_products",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("external_product_id", sa.String(240), nullable=False),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("raw_title", sa.Text()),
        sa.Column("product_variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="RESTRICT")),
        sa.Column("status", sa.String(24), nullable=False, server_default="discovered"),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("store_id", "external_product_id", name="uq_store_products_external_identity"),
        sa.CheckConstraint(
            "status IN ('discovered','active','inactive','unavailable','quarantined','unresolved')",
            name="ck_store_products_status",
        ),
    )
    op.create_index("ix_store_products_status_last_seen", "store_products", ["status", "last_seen_at"])
    op.create_index("ix_store_products_product_variant_id", "store_products", ["product_variant_id"])

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        # SQLite can add a nullable REFERENCES column without rebuilding the
        # table. Avoid batch recreation here: offers already references
        # ingestion_raw, so dropping/recreating ingestion_raw would violate FK
        # enforcement while the migration is running.
        op.execute(
            "ALTER TABLE offers ADD COLUMN store_product_id CHAR(32) "
            "REFERENCES store_products(id) ON DELETE RESTRICT"
        )
        op.create_index("ix_offers_store_product_id", "offers", ["store_product_id"])
        op.execute(
            "ALTER TABLE ingestion_raw ADD COLUMN store_product_id CHAR(32) "
            "REFERENCES store_products(id) ON DELETE RESTRICT"
        )
        op.create_index("ix_ingestion_raw_store_product_id", "ingestion_raw", ["store_product_id"])
    else:
        op.add_column("offers", sa.Column("store_product_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            "fk_offers_store_product_id_store_products",
            "offers", "store_products", ["store_product_id"], ["id"], ondelete="RESTRICT",
        )
        op.create_index("ix_offers_store_product_id", "offers", ["store_product_id"])

        op.add_column("ingestion_raw", sa.Column("store_product_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            "fk_ingestion_raw_store_product_id_store_products",
            "ingestion_raw", "store_products", ["store_product_id"], ["id"], ondelete="RESTRICT",
        )
        op.create_index("ix_ingestion_raw_store_product_id", "ingestion_raw", ["store_product_id"])

    op.create_table(
        "brand_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("brand_id", sa.Uuid(), sa.ForeignKey("brands.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias_text", sa.String(220), nullable=False),
        sa.Column("normalized_alias", sa.String(220), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False, server_default="und"),
        sa.Column("alias_type", sa.String(40), nullable=False, server_default="alternate_name"),
        sa.Column("source", sa.String(80), nullable=False, server_default="manual"),
        sa.Column("verification_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("brand_id", "normalized_alias", "locale", name="uq_brand_alias_identity"),
        sa.CheckConstraint(
            "verification_status IN ('pending','verified','rejected','ambiguous','legacy')",
            name="ck_brand_aliases_verification_status",
        ),
    )
    op.create_index("ix_brand_aliases_normalized", "brand_aliases", ["normalized_alias"])

    op.create_table(
        "fragrance_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("fragrance_id", sa.Uuid(), sa.ForeignKey("fragrances.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alias_text", sa.String(240), nullable=False),
        sa.Column("normalized_alias", sa.String(240), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False, server_default="und"),
        sa.Column("alias_type", sa.String(40), nullable=False, server_default="alternate_name"),
        sa.Column("source", sa.String(80), nullable=False, server_default="manual"),
        sa.Column("verification_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("fragrance_id", "normalized_alias", "locale", name="uq_fragrance_alias_identity"),
        sa.CheckConstraint(
            "verification_status IN ('pending','verified','rejected','ambiguous','legacy')",
            name="ck_fragrance_aliases_verification_status",
        ),
    )
    op.create_index("ix_fragrance_aliases_normalized", "fragrance_aliases", ["normalized_alias"])

    op.create_table(
        "product_variant_aliases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="SET NULL")),
        sa.Column("alias_text", sa.String(320), nullable=False),
        sa.Column("normalized_alias", sa.String(320), nullable=False),
        sa.Column("locale", sa.String(16), nullable=False, server_default="und"),
        sa.Column("alias_type", sa.String(40), nullable=False, server_default="retailer_title"),
        sa.Column("source", sa.String(80), nullable=False, server_default="manual"),
        sa.Column("verification_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "verification_status IN ('pending','verified','rejected','ambiguous','legacy')",
            name="ck_product_variant_aliases_verification_status",
        ),
    )
    op.create_index("ix_product_variant_aliases_normalized", "product_variant_aliases", ["normalized_alias"])
    op.create_index(
        "uq_product_variant_aliases_global",
        "product_variant_aliases",
        ["product_variant_id", "normalized_alias", "locale"],
        unique=True,
        postgresql_where=sa.text("store_id IS NULL"),
        sqlite_where=sa.text("store_id IS NULL"),
    )
    op.create_index(
        "uq_product_variant_aliases_store",
        "product_variant_aliases",
        ["product_variant_id", "normalized_alias", "locale", "store_id"],
        unique=True,
        postgresql_where=sa.text("store_id IS NOT NULL"),
        sqlite_where=sa.text("store_id IS NOT NULL"),
    )

    op.create_table(
        "product_variant_gtins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("product_variant_id", sa.Uuid(), sa.ForeignKey("product_variants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gtin", sa.String(14), nullable=False),
        sa.Column("normalized_gtin", sa.String(14), nullable=False),
        sa.Column("market", sa.String(2)),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("verification_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("evidence", sa.JSON()),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("verified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("product_variant_id", "normalized_gtin", name="uq_product_variant_gtin_identity"),
        sa.CheckConstraint(
            "length(normalized_gtin) IN (8,12,13,14)",
            name="ck_product_variant_gtins_normalized_gtin_length",
        ),
        sa.CheckConstraint(
            "verification_status IN ('pending','verified','rejected','ambiguous','legacy')",
            name="ck_product_variant_gtins_verification_status",
        ),
    )
    op.create_index("ix_product_variant_gtins_normalized", "product_variant_gtins", ["normalized_gtin"])
    op.create_index(
        "uq_product_variant_gtins_verified",
        "product_variant_gtins",
        ["normalized_gtin"],
        unique=True,
        postgresql_where=sa.text("verification_status = 'verified'"),
        sqlite_where=sa.text("verification_status = 'verified'"),
    )

    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ingestion_run_id", sa.Uuid(), sa.ForeignKey("ingestion_runs.id", ondelete="SET NULL")),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("query_text", sa.Text()),
        sa.Column("discovery_method", sa.String(40), nullable=False),
        sa.Column("source_url", sa.Text()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("pages_scanned", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("products_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("products_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("products_existing", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("errors", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.CheckConstraint(
            "status IN ('running','completed','partial','failed')",
            name="ck_discovery_runs_status",
        ),
        sa.CheckConstraint(
            "pages_scanned >= 0 AND products_seen >= 0 AND products_new >= 0 AND products_existing >= 0",
            name="ck_discovery_runs_nonnegative_counters",
        ),
    )
    op.create_index("ix_discovery_runs_store_started_at", "discovery_runs", ["store_id", "started_at"])
    op.create_index("ix_discovery_runs_ingestion_run_id", "discovery_runs", ["ingestion_run_id"])

    op.create_table(
        "extraction_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("ingestion_run_id", sa.Uuid(), sa.ForeignKey("ingestion_runs.id", ondelete="SET NULL")),
        sa.Column("store_id", sa.Uuid(), sa.ForeignKey("stores.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("store_product_id", sa.Uuid(), sa.ForeignKey("store_products.id", ondelete="SET NULL")),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("http_status", sa.Integer()),
        sa.Column("parser_version", sa.String(80)),
        sa.Column("response_sha256", sa.String(64)),
        sa.Column("extracted_fields", sa.JSON()),
        sa.Column("error_code", sa.String(100)),
        sa.Column("error_detail", sa.Text()),
        sa.CheckConstraint(
            "status IN ('running','completed','partial','failed','rejected')",
            name="ck_extraction_runs_status",
        ),
        sa.CheckConstraint(
            "http_status IS NULL OR (http_status >= 100 AND http_status <= 599)",
            name="ck_extraction_runs_http_status_range",
        ),
    )
    op.create_index("ix_extraction_runs_store_started_at", "extraction_runs", ["store_id", "started_at"])
    op.create_index("ix_extraction_runs_store_product_started_at", "extraction_runs", ["store_product_id", "started_at"])
    op.create_index("ix_extraction_runs_ingestion_run_id", "extraction_runs", ["ingestion_run_id"])

    _backfill_store_products(op.get_bind())
    _backfill_legacy_gtins(op.get_bind())


def downgrade():
    op.drop_index("ix_extraction_runs_ingestion_run_id", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_store_product_started_at", table_name="extraction_runs")
    op.drop_index("ix_extraction_runs_store_started_at", table_name="extraction_runs")
    op.drop_table("extraction_runs")

    op.drop_index("ix_discovery_runs_ingestion_run_id", table_name="discovery_runs")
    op.drop_index("ix_discovery_runs_store_started_at", table_name="discovery_runs")
    op.drop_table("discovery_runs")

    op.drop_index("uq_product_variant_gtins_verified", table_name="product_variant_gtins")
    op.drop_index("ix_product_variant_gtins_normalized", table_name="product_variant_gtins")
    op.drop_table("product_variant_gtins")

    op.drop_index("uq_product_variant_aliases_store", table_name="product_variant_aliases")
    op.drop_index("uq_product_variant_aliases_global", table_name="product_variant_aliases")
    op.drop_index("ix_product_variant_aliases_normalized", table_name="product_variant_aliases")
    op.drop_table("product_variant_aliases")

    op.drop_index("ix_fragrance_aliases_normalized", table_name="fragrance_aliases")
    op.drop_table("fragrance_aliases")

    op.drop_index("ix_brand_aliases_normalized", table_name="brand_aliases")
    op.drop_table("brand_aliases")

    with op.batch_alter_table("ingestion_raw") as batch:
        batch.drop_index("ix_ingestion_raw_store_product_id")
        batch.drop_constraint("fk_ingestion_raw_store_product_id_store_products", type_="foreignkey")
        batch.drop_column("store_product_id")

    with op.batch_alter_table("offers") as batch:
        batch.drop_index("ix_offers_store_product_id")
        batch.drop_constraint("fk_offers_store_product_id_store_products", type_="foreignkey")
        batch.drop_column("store_product_id")

    op.drop_index("ix_store_products_product_variant_id", table_name="store_products")
    op.drop_index("ix_store_products_status_last_seen", table_name="store_products")
    op.drop_table("store_products")
