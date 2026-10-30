"""Runtime entry point for the isolated PostgreSQL Offer Engine.

This module is opt-in. It never reuses or mutates the legacy SQLite catalog.
The caller must provision the separate PostgreSQL database and explicitly
apply the additive migration before running the worker.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

import psycopg

from .adapters import RetailerConnector
from .connectors.deloox import DelooxConnector
from .connectors.notino import NotinoFeedConnector
from .connectors.parsed_search import ParsedSearchConnector
from .connectors.notino import NotinoFeedConnector
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


def _dsn(value: str | None = None) -> str:
    result = (value or os.environ.get("SCENTHUNTER_OFFER_ENGINE_DSN") or "").strip()
    if not result:
        raise RuntimeError("SCENTHUNTER_OFFER_ENGINE_DSN is required for the isolated Offer Engine")
    return result


def apply_migration(dsn: str | None = None) -> None:
    """Apply the additive sh_* schema to the dedicated PostgreSQL database."""
    connection = psycopg.connect(_dsn(dsn))
    try:
        migration_files = sorted(MIGRATIONS_DIR.glob("*.sql"))
        if not migration_files:
            raise RuntimeError("offer_engine_migrations_missing")
        with connection.cursor() as cursor:
            for migration_path in migration_files:
                cursor.execute(migration_path.read_text(encoding="utf-8"))
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
    connectors: Iterable[RetailerConnector] | None = None,
) -> EngineRunResult:
    """Run retailer connectors against the canonical catalog and isolated DB."""
    if not query.strip():
        raise ValueError("query must not be empty")
    connection_string = _dsn(dsn)
    catalog = CatalogRepository.from_file(CATALOG_PATH)
    matcher = CanonicalMatcher(catalog)
    connections: list[psycopg.Connection] = []

    def repository_factory(_connector: RetailerConnector) -> OfferRepository:
        connection = psycopg.connect(connection_string)
        connections.append(connection)
        return OfferRepository(connection, canonical_catalog=catalog)

    try:
        runner = OfferEngineRunner(matcher, repository_factory)
        if connectors is not None:
            active_connectors = list(connectors)
        else:
            active_connectors = [
                DelooxConnector(),
                ParsedSearchConnector("bplatz", "scrapers.bplatz.scraper", "DE"),
                ParsedSearchConnector("easycosmetic", "scrapers.easycosmetic.scraper", "DE"),
                ParsedSearchConnector("orioudh", "scrapers.orioudh.scraper", "EU"),
                ParsedSearchConnector("parfumcity", "scrapers.parfumcity.scraper", "NL"),
                ParsedSearchConnector("parfumzentrum", "scrapers.parfumzentrum.scraper", "DE"),
                ParsedSearchConnector("perfumemarket", "scrapers.perfumemarket.scraper", "NL"),
                ParsedSearchConnector("sabina", "scrapers.sabina.scraper", "ES"),
            ]
            # Notino's approved CJ/VIV feed is an authenticated, structured source.
            # Add it only when all credentials are configured; never make the
            # entire run fail just because this optional feed is not provisioned.
            if NotinoFeedConnector.configured():
                active_connectors.insert(1, NotinoFeedConnector())
        return runner.run(active_connectors, query)
    finally:
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
