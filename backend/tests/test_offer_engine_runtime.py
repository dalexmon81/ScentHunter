from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.offer_engine import runtime
from backend.offer_engine.runner import EngineRunResult
from backend.offer_engine.contracts import Availability, OfferObservation, RetailerListing, Verification
from backend.offer_engine.repository import OfferRepository
from backend.offer_engine.read_repository import OfferReadRepository
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


class FakeCursor:
    def __init__(self):
        self.sql = []
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def execute(self, sql):
        self.sql.append(sql)


class FakeConnection:
    def __init__(self):
        self.cursor_instance = FakeCursor()
        self.commits = 0
        self.rollbacks = 0
        self.closed = False
    def cursor(self):
        return self.cursor_instance
    def commit(self):
        self.commits += 1
    def rollback(self):
        self.rollbacks += 1
    def close(self):
        self.closed = True


class OfferEngineRuntimeTests(unittest.TestCase):
    def test_dsn_is_required_and_can_be_injected(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "SCENTHUNTER_OFFER_ENGINE_DSN"):
                runtime._dsn()
        self.assertEqual(runtime._dsn("postgresql://test"), "postgresql://test")

    def test_default_connection_factory_uses_isolated_sqlite_file(self):
        import sqlite3
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "offer_engine.sqlite3"
            connection = runtime.connect_offer_engine_db(db_path=path)
            try:
                self.assertIsInstance(connection, sqlite3.Connection)
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertTrue(path.exists())
            finally:
                connection.close()

    def test_sqlite_migration_creates_isolated_offer_tables(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "offer_engine.sqlite3"
            runtime.apply_migration(db_path=path)
            connection = runtime.connect_offer_engine_db(db_path=path)
            try:
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertIn("sh_products", tables)
                self.assertIn("sh_current_offers", tables)
                self.assertNotIn("store_products", tables)
            finally:
                connection.close()

    def test_migration_commits_and_closes_dedicated_connection(self):
        connection = FakeConnection()
        with patch.object(runtime.psycopg, "connect", return_value=connection) as connect:
            runtime.apply_migration("postgresql://test")
        connect.assert_called_once_with("postgresql://test")
        self.assertTrue(any("CREATE TABLE IF NOT EXISTS sh_products" in sql for sql in connection.cursor_instance.sql))
        self.assertTrue(any("DROP CONSTRAINT IF EXISTS sh_retailer_listings_retailer_id_product_url_key" in sql for sql in connection.cursor_instance.sql))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.rollbacks, 0)
        self.assertTrue(connection.closed)

    def test_sqlite_migration_creates_isolated_schema(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            db_path = Path(directory) / "offer_engine.sqlite3"
            runtime.apply_migration(db_path=db_path)
            connection = runtime.connect_offer_engine_db(db_path=db_path)
            try:
                tables = {
                    row[0] for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    ).fetchall()
                }
                self.assertTrue({"sh_products", "sh_variants", "sh_retailer_listings", "sh_current_offers"} <= tables)
                self.assertNotIn("store_products", tables)
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            finally:
                connection.close()

    def test_sqlite_repository_publishes_sold_out_variant_without_price(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            db_path = Path(directory) / "offer_engine.sqlite3"
            runtime.apply_migration(db_path=db_path)
            connection = runtime.connect_offer_engine_db(db_path=db_path)
            try:
                root = Path(__file__).resolve().parents[2]
                catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
                product = catalog.get("SH-0031")
                variant = next(item for item in product.variants if item.variant_id == "VAR-f5aff76b4bb5de8a")
                url = "https://www.deloox.be/produit/1385920/liquid-brun-limited-150.html"
                listing = RetailerListing(
                    retailer="deloox", external_id="1385920", product_url=url,
                    raw_title="French Avenue Liquid Brun Limited Edition 150 ml",
                    raw_brand="French Avenue", raw_size_ml=150, market="BE",
                )
                observation = OfferObservation(
                    listing_key="deloox:1385920", observed_at=datetime.now(timezone.utc),
                    price=None, currency="EUR", availability=Availability.OUT_OF_STOCK,
                    source="product_page", verification=Verification.VERIFIED,
                    product_id=product.product_id, variant_id=variant.variant_id,
                    evidence_url=url, evidence_hash="sha256:sqlite-runtime",
                )
                result = OfferRepository(connection, canonical_catalog=catalog).record(listing, observation)
                self.assertTrue(result["published"])
                current = OfferReadRepository(connection).search("Liquid Brun", market="BE")
                self.assertEqual(len(current), 1)
                self.assertEqual(current[0]["variant_id"], variant.variant_id)
                self.assertEqual(current[0]["availability"], "out_of_stock")
                self.assertIsNone(current[0]["price"])
            finally:
                connection.close()

    def test_runner_connection_is_closed_after_execution(self):
        connection = FakeConnection()
        class FakeRunner:
            def __init__(self, matcher, repository_factory):
                self.repository_factory = repository_factory
            def run(self, connectors, query):
                repository = self.repository_factory(next(iter(connectors)))
                self.assert_repository = repository
                return EngineRunResult([])
        with (
            patch.object(runtime.psycopg, "connect", return_value=connection),
            patch.object(runtime.CatalogRepository, "from_file", return_value=object()),
            patch.object(runtime, "CanonicalMatcher", return_value=object()),
            patch.object(runtime, "OfferEngineRunner", FakeRunner),
        ):
            result = runtime.run_offer_engine("Liquid Brun", dsn="postgresql://test")
        self.assertEqual(result.connectors, [])
        self.assertTrue(connection.closed)


if __name__ == "__main__":
    unittest.main()
