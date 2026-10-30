"""Runtime entry point for the isolated Offer Engine.

Fly deployments use a dedicated SQLite file on the existing persistent volume
by default. A separate PostgreSQL DSN can be supplied when desired. Neither
backend touches the legacy catalog tables.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Iterable, Any

import psycopg

from .adapters import RetailerConnector
from .connectors.deloox import DelooxConnector
from .connectors.notino import NotinoFeedConnector
from .connectors.parsed_search import ParsedSearchConnector
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
    connections: list[Any] = []

    def repository_factory(_connector: RetailerConnector) -> OfferRepository:
        connection = connect_offer_engine_db(dsn=dsn, db_path=db_path)
        connections.append(connection)
        return OfferRepository(connection, canonical_catalog=catalog)

    try:
        runner = OfferEngineRunner(matcher, repository_factory)
        if connectors is None:
            configured_connectors = [
                DelooxConnector(),
                NotinoFeedConnector(),
                ParsedSearchConnector("bplatz", "scrapers.bplatz.scraper", "DE"),
                ParsedSearchConnector("easycosmetic", "scrapers.easycosmetic.scraper", "DE"),
                ParsedSearchConnector("orioudh", "scrapers.orioudh.scraper", "EU"),
                ParsedSearchConnector("parfumcity", "scrapers.parfumcity.scraper", "NL"),
                ParsedSearchConnector("parfumzentrum", "scrapers.parfumzentrum.scraper", "DE"),
                ParsedSearchConnector("perfumemarket", "scrapers.perfumemarket.scraper", "NL"),
                ParsedSearchConnector("sabina", "scrapers.sabina.scraper", "ES"),
            ]
        else:
            configured_connectors = list(connectors)
        return runner.run(configured_connectors, query)
    finally:
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
