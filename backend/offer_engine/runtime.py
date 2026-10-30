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

from backend.offer_engine.adapters import RetailerConnector
from backend.offer_engine.connectors.deloox import DelooxConnector
from backend.offer_engine.repository import OfferRepository
from backend.offer_engine.runner import EngineRunResult, OfferEngineRunner
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


ROOT = Path(__file__).resolve().parents[2]
CATALOG_PATH = ROOT / "backend" / "product_catalog.json"
MIGRATION_PATH = ROOT / "backend" / "offer_engine" / "migrations" / "001_offer_engine.sql"


def _dsn(value: str | None = None) -> str:
    result = (value or os.environ.get("SCENTHUNTER_OFFER_ENGINE_DSN") or "").strip()
    if not result:
        raise RuntimeError("SCENTHUNTER_OFFER_ENGINE_DSN is required for the isolated Offer Engine")
    return result


def apply_migration(dsn: str | None = None) -> None:
    """Apply the additive sh_* schema to the dedicated PostgreSQL database."""
    connection = psycopg.connect(_dsn(dsn))
    try:
        migration = MIGRATION_PATH.read_text(encoding="utf-8")
        with connection.cursor() as cursor:
            cursor.execute(migration)
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
        return runner.run(connectors or [DelooxConnector()], query)
    finally:
        for connection in connections:
            try:
                connection.close()
            except Exception:
                pass
