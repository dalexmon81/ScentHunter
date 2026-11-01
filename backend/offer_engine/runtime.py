"""Runtime entry point for the isolated Offer Engine.

Fly deployments use a dedicated SQLite file on the existing persistent volume
by default. A separate PostgreSQL DSN can be supplied when desired. Neither
backend touches the legacy catalog tables.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Iterable, Any

import psycopg

from .adapters import RetailerConnector
from .connectors.deloox import DelooxConnector
from .connectors.notino import NotinoFeedConnector
from .connectors.parsed_search import ParsedSearchConnector
from .connectors.amazon_creators import AmazonCreatorsConnector
try:
    from scrapers import amazon_creators_api
except ModuleNotFoundError:
    from backend.scrapers import amazon_creators_api
from .repository import OfferRepository
from .runner import EngineRunResult, OfferEngineRunner
try:
    from scenthunter_next_engine.canonical_matcher import CanonicalMatcher
    from scenthunter_next_engine.catalog_repository import CatalogRepository
except ModuleNotFoundError:
    from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
    from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "backend" / "product_catalog.json"
MIGRATIONS_DIR = ROOT / "backend" / "offer_engine" / "migrations"
SQLITE_MIGRATION_PATH = ROOT / "backend" / "offer_engine" / "migrations" / "001_offer_engine_sqlite.sql"


def _dsn(value: str | None = None) -> str:
    result = (value or os.environ.get("SCENTHUNTER_OFFER_ENGINE_DSN") or "").strip()
    if not result:
        raise RuntimeError("SCENTHUNTER_OFFER_ENGINE_DSN is not configured")
    return result


def _sqlite_path(value: str | Path | None = None) -> Path:
    configured = value or os.environ.get("SCENTHUNTER_OFFER_ENGINE_DB")
    if configured:
        path = Path(configured).expanduser()
    else:
        catalog_db = Path(
            os.environ.get("SCENTHUNTER_CATALOG_DB", str(ROOT / "backend" / "store_catalog.sqlite3"))
        ).expanduser()
        path = catalog_db.with_name("offer_engine.sqlite3")
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    return path


def connect_offer_engine_db(
    *,
    dsn: str | None = None,
    db_path: str | Path | None = None,
) -> Any:
    """Open the dedicated Offer Engine DB: PostgreSQL when configured, SQLite otherwise."""
    configured_dsn = (dsn or (os.environ.get("SCENTHUNTER_OFFER_ENGINE_DSN") if db_path is None else "") or "").strip()
    if configured_dsn:
        return psycopg.connect(configured_dsn)
    connection = sqlite3.connect(str(_sqlite_path(db_path)), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    return connection


def apply_migration(
    dsn: str | None = None,
    *,
    db_path: str | Path | None = None,
) -> None:
    """Apply the additive sh_* schema to the dedicated Offer Engine database."""
    configured_dsn = (dsn or (os.environ.get("SCENTHUNTER_OFFER_ENGINE_DSN") if db_path is None else "") or "").strip()
    connection = connect_offer_engine_db(dsn=configured_dsn or None, db_path=db_path)
    try:
        if configured_dsn:
            migration_paths = sorted(
                path for path in MIGRATIONS_DIR.glob("*.sql")
                if not path.name.endswith("_sqlite.sql")
            )
            if not migration_paths:
                raise RuntimeError("offer_engine_postgres_migrations_missing")
            with connection.cursor() as cursor:
                for migration_path in migration_paths:
                    cursor.execute(migration_path.read_text(encoding="utf-8"))
            connection.commit()
        else:
            migration = SQLITE_MIGRATION_PATH.read_text(encoding="utf-8")
            connection.executescript(migration)
            connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()



def seed_canonical_catalog(
    *,
    dsn: str | None = None,
    db_path: str | Path | None = None,
    catalog_path: str | Path = CATALOG_PATH,
) -> dict[str, Any]:
    """Idempotently stage explicit canonical products and variants.

    Missing images and products without declared variants are non-blocking for
    identity staging: they remain non-purchasable until a real variant is
    explicitly catalogued. Structural corruption (duplicate IDs, orphan or
    malformed variants, missing brand/name) blocks the whole transaction.
    This routine never creates IDs, sizes, aliases, GTINs, or offer observations.
    """
    try:
        from scenthunter_next_engine.catalog_preflight import audit_catalog_data
    except ModuleNotFoundError:
        from backend.scenthunter_next_engine.catalog_preflight import audit_catalog_data

    source = Path(catalog_path).expanduser().resolve()
    with source.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    audit = audit_catalog_data(raw)
    allowed_findings = {"products_without_variants", "products_missing_canonical_image"}
    blockers = [
        finding for finding in audit.get("findings", [])
        if finding.get("code") not in allowed_findings
    ]
    if blockers or audit.get("duplicate_product_ids") or audit.get("duplicate_variant_ids"):
        raise RuntimeError(f"canonical_catalog_preflight_failed: {blockers or 'duplicate_ids'}")

    catalog = CatalogRepository.from_file(source)
    if (
        catalog.skipped_product_count()
        or catalog.skipped_variant_count()
        or catalog.product_count() != audit.get("product_count")
        or catalog.variant_count() != audit.get("variant_count")
    ):
        raise RuntimeError("canonical_catalog_parse_reconciliation_failed")

    connection = connect_offer_engine_db(dsn=dsn, db_path=db_path)
    sqlite_backend = isinstance(connection, sqlite3.Connection)
    cursor = connection.cursor()

    def execute(sql: str, params: tuple[Any, ...]) -> None:
        if sqlite_backend:
            sql = sql.replace("%s", "?")
        cursor.execute(sql, params)

    products_written = 0
    variants_written = 0
    try:
        for product in catalog.all_products():
            execute(
                """INSERT INTO sh_products(product_id, brand, canonical_name, concentration)
                   VALUES (%s,%s,%s,%s)
                   ON CONFLICT (product_id) DO UPDATE SET
                     brand=EXCLUDED.brand, canonical_name=EXCLUDED.canonical_name,
                     concentration=EXCLUDED.concentration""",
                (product.product_id, product.brand, product.name, product.concentration),
            )
            products_written += 1
            for variant in product.variants:
                if variant.size_ml is None or int(variant.size_ml) <= 0:
                    raise RuntimeError(f"canonical_variant_missing_valid_size: {variant.variant_id}")
                labels = " ".join((variant.label or "", *variant.aliases)).casefold()
                package_type = "limited_edition" if "limited edition" in labels else "standard"
                execute(
                    """INSERT INTO sh_variants(variant_id, product_id, size_ml, concentration, package_type)
                       VALUES (%s,%s,%s,%s,%s)
                       ON CONFLICT (variant_id) DO UPDATE SET
                         product_id=EXCLUDED.product_id, size_ml=EXCLUDED.size_ml,
                         concentration=EXCLUDED.concentration, package_type=EXCLUDED.package_type""",
                    (variant.variant_id, product.product_id, int(variant.size_ml),
                     product.concentration, package_type),
                )
                variants_written += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    return {
        "status": "staged",
        "products_upserted": products_written,
        "variants_upserted": variants_written,
        "products_without_variants": audit.get("products_without_variants", 0),
        "products_missing_canonical_image": next(
            (item["count"] for item in audit.get("findings", [])
             if item.get("code") == "products_missing_canonical_image"), 0
        ),
        "offers_published": 0,
        "catalog_mutated": False,
        "automatic_identity_repairs": 0,
        "note": "Identity staging only; no retailer offers or inferred variants were created.",
    }


def run_offer_engine(
    query: str,
    *,
    dsn: str | None = None,
    db_path: str | Path | None = None,
    connectors: Iterable[RetailerConnector] | None = None,
) -> EngineRunResult:
    """Run retailer connectors against the canonical catalog and isolated DB."""
    if not query.strip():
        raise ValueError("query must not be empty")
    catalog = CatalogRepository.from_file(CATALOG_PATH)
    matcher = CanonicalMatcher(catalog)
    def repository_factory(_connector: RetailerConnector) -> OfferRepository:
        # Each connector owns and closes its own connection. This lets the
        # runner return fast-store results on time while a slow store finishes
        # its isolated task in the background.
        connection = connect_offer_engine_db(dsn=dsn, db_path=db_path)
        return OfferRepository(connection, canonical_catalog=catalog)

    runner = OfferEngineRunner(
        matcher,
        repository_factory,
        max_workers=8,
        connector_timeout_seconds=float(
            os.environ.get("SCENTHUNTER_OFFER_ENGINE_CONNECTOR_TIMEOUT_SECONDS", "60")
        ),
    )
    if connectors is None:
        configured_connectors = [DelooxConnector()]
        # Keep all intended retailers visible in diagnostics even when an
        # integration is not configured. The connector fails closed with an
        # explicit reason and cannot publish an offer without its authorized
        # source credentials.
        configured_connectors.append(NotinoFeedConnector())
        # Amazon is admitted only through the approved Creators API. These
        # connectors report configuration failures when unavailable; legacy
        # public-search/Bing-snippet scrapers are never admitted as offers.
        for amazon_market in ("de", "fr"):
            configured_connectors.append(AmazonCreatorsConnector(amazon_market))
        configured_connectors.extend([
            ParsedSearchConnector("bplatz", "scrapers.bplatz.scraper", "DE"),
            ParsedSearchConnector("easycosmetic", "scrapers.easycosmetic.scraper", "DE"),
            ParsedSearchConnector("orioudh", "scrapers.orioudh.scraper", "EU"),
            ParsedSearchConnector("parfumcity", "scrapers.parfumcity.scraper", "NL"),
            ParsedSearchConnector("parfumzentrum", "scrapers.parfumzentrum.scraper", "DE"),
            ParsedSearchConnector("perfumemarket", "scrapers.perfumemarket.scraper", "NL"),
            ParsedSearchConnector("sabina", "scrapers.sabina.scraper", "ES"),
        ])
    else:
        configured_connectors = list(connectors)

    # A deployment may deliberately isolate one retailer while diagnosing its
    # end-to-end search path. This is used only by the dedicated Pilot config;
    # unset means the normal full retailer set.
    retailer_filter = {
        item.strip().lower()
        for item in os.environ.get("SCENTHUNTER_OFFER_ENGINE_RETAILERS", "").split(",")
        if item.strip()
    }
    if retailer_filter:
        available = {str(item.retailer).strip().lower() for item in configured_connectors}
        unknown = sorted(retailer_filter - available)
        if unknown:
            raise RuntimeError("unknown_offer_engine_retailers: " + ",".join(unknown))
        configured_connectors = [
            item for item in configured_connectors
            if str(item.retailer).strip().lower() in retailer_filter
        ]
    return runner.run(configured_connectors, query)
