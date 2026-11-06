from __future__ import annotations

import csv
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scenthunter_next_engine.catalog_repository import CatalogRepository
from scenthunter_next_engine.models import CanonicalProduct, CanonicalVariant
from scenthunter_next_engine.phase0_baseline_jobs import (
    COLUMNS,
    STORES,
    SMOKE_STORES,
    generate_smoke_csv,
    claim_next_job,
    connect,
    create_job,
    ensure_schema,
    generate_csv,
    get_job,
    iter_store_rows,
    recover_stale_jobs,
    _store_count,
)


class Phase0PersistentJobTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db_path = self.root / "catalog.sqlite3"
        self.patch_jobs_db = patch(
            "scenthunter_next_engine.phase0_baseline_jobs.jobs_database_path",
            return_value=self.db_path,
        )
        self.patch_catalog_db = patch(
            "scenthunter_next_engine.phase0_baseline_jobs.catalog_database_path",
            return_value=self.db_path,
        )
        self.patch_jobs_db.start()
        self.patch_catalog_db.start()
        conn = connect()
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            ensure_schema(conn)
            conn.executescript(
                """
                CREATE TABLE store_products (
                    store TEXT NOT NULL, url TEXT NOT NULL, name TEXT, brand TEXT,
                    sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL, concentration TEXT,
                    price REAL, currency TEXT, availability TEXT, fetched_at REAL,
                    PRIMARY KEY(store,url)
                );
                CREATE TABLE store_product_variants (
                    store TEXT NOT NULL, url TEXT NOT NULL, variant_key TEXT NOT NULL,
                    name TEXT, brand TEXT, sku TEXT, gtin TEXT, mpn TEXT,
                    size_ml REAL, concentration TEXT, price REAL, currency TEXT,
                    availability TEXT, fetched_at REAL, variant_url TEXT,
                    PRIMARY KEY(store,url,variant_key)
                );
                """
            )
            conn.commit()
        finally:
            conn.close()

    def tearDown(self):
        self.patch_jobs_db.stop()
        self.patch_catalog_db.stop()
        self.temp.cleanup()

    def test_job_is_durable_and_claim_is_atomic(self):
        created = create_job()
        self.assertEqual(created["status"], "queued")
        queued = get_job(created["job_id"])
        self.assertEqual(queued["status"], "queued")
        self.assertEqual(queued["total_stores"], 9)

        claimed = claim_next_job("worker-a")
        self.assertEqual(claimed["id"], created["job_id"])
        self.assertEqual(claimed["status"], "running")
        self.assertEqual(claimed["worker_id"], "worker-a")
        self.assertIsNone(claim_next_job("worker-b"))

    def test_legacy_running_eleven_store_job_is_retired(self):
        created = create_job()
        conn = connect()
        try:
            conn.execute(
                """UPDATE phase0_baseline_jobs
                      SET status='running', total_stores=11,
                          started_at='2026-11-01T00:00:00+00:00'
                    WHERE id=?""",
                (created["job_id"],),
            )
            conn.commit()
            ensure_schema(conn)
            row = conn.execute(
                "SELECT status,total_stores,error_message FROM phase0_baseline_jobs WHERE id=?",
                (created["job_id"],),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["total_stores"], 11)
        self.assertIn("scope changed", row["error_message"])

    def test_stale_running_job_is_marked_failed_but_queued_job_survives(self):
        queued = create_job()
        running = create_job()
        conn = connect()
        try:
            ensure_schema(conn)
            conn.execute(
                """UPDATE phase0_baseline_jobs
                      SET status='running', started_at='2000-01-01T00:00:00+00:00',
                          heartbeat_at='2000-01-01T00:00:00+00:00'
                    WHERE id=?""",
                (running["job_id"],),
            )
            conn.commit()
        finally:
            conn.close()

        self.assertEqual(recover_stale_jobs(), 1)
        self.assertEqual(get_job(running["job_id"])["status"], "failed")
        self.assertEqual(get_job(queued["job_id"])["status"], "queued")

    def test_streaming_rows_include_variant_and_base_fallback_once(self):
        conn = connect()
        try:
            conn.execute(
                """INSERT INTO store_products
                   (store,url,name,brand,price,currency,availability)
                   VALUES('bplatz','https://shop.test/p','Fragrance 100 ml',
                          'Brand',80,'EUR','in_stock')"""
            )
            conn.execute(
                """INSERT INTO store_product_variants
                   (store,url,variant_key,name,brand,size_ml,price,currency,
                    availability,variant_url)
                   VALUES('bplatz','https://shop.test/p','100ml','Fragrance 100 ml',
                          'Brand',100,80,'EUR','in_stock','https://shop.test/p?size=100')"""
            )
            conn.execute(
                """INSERT INTO store_products
                   (store,url,name,brand,price,currency,availability)
                   VALUES('deloox','https://deloox.test/p','Another Fragrance',
                          'Brand',45,'EUR','out_of_stock')"""
            )
            conn.commit()
            self.assertEqual(_store_count(conn, "bplatz", True), 1)
            self.assertEqual(_store_count(conn, "deloox", True), 1)
            bplatz_rows = list(iter_store_rows(conn, "bplatz", True))
            deloox_rows = list(iter_store_rows(conn, "deloox", True))
            self.assertEqual(len(bplatz_rows), 1)
            self.assertEqual(bplatz_rows[0]["source"], "store_product_variants")
            self.assertEqual(bplatz_rows[0]["offer_url"], "https://shop.test/p?size=100")
            self.assertEqual(len(deloox_rows), 1)
            self.assertEqual(deloox_rows[0]["source"], "store_products")
        finally:
            conn.close()

    def test_smoke_csv_contains_exactly_nine_active_retailers(self):
        output = self.root / "phase0" / "smoke" / "smoke.csv"
        result = generate_smoke_csv({"output_path": str(output)})
        with output.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(SMOKE_STORES, STORES)
        self.assertEqual(result["rows_written"], 9)
        self.assertEqual([row["store"] for row in rows], list(STORES))
        self.assertFalse({"amazon_de", "amazon_fr"} & {row["store"] for row in rows})

    def test_baseline_refuses_legacy_sqlite_catalog(self):
        output = self.root / "phase0" / "baseline" / "job-1.csv"
        job = {"id": "job-1", "output_path": str(output)}
        with patch.dict(os.environ, {
            "SCENTHUNTER_CATALOG_DATABASE_URL": "sqlite:///" + str(self.db_path),
            "SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL": "1",
        }):
            with self.assertRaisesRegex(RuntimeError, "requires a PostgreSQL catalog URL"):
                generate_csv(job, "test-worker")
        self.assertFalse(output.exists())


    def test_postgres_export_writes_a_real_canonical_offer_row(self):
        import queue
        import uuid
        from datetime import datetime, timedelta, timezone
        from decimal import Decimal
        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from app.db import make_engine
        from app.models import Brand, Fragrance, Offer, ProductVariant, Store
        from scenthunter_next_engine.phase0_baseline_jobs import _export_store_chunk

        engine = make_engine()
        self.assertEqual(engine.dialect.name, "postgresql")
        suffix = uuid.uuid4().hex[:12]
        brand = fragrance = variant = offer = store = None
        chunk = self.root / "postgres-export.csv"
        result_queue = queue.Queue()
        try:
            with Session(engine) as session:
                store = Store(
                    name=f"Phase 0 Test Store {suffix}",
                    slug=f"phase0-test-{suffix}",
                    domain="phase0-test.invalid",
                    country="FR",
                    currency="EUR",
                    status="active",
                )
                session.add(store)
                session.flush()
                brand = Brand(
                    name=f"Baseline Test {suffix}",
                    slug=f"baseline-test-{suffix}",
                    normalized_name=f"baseline test {suffix}",
                )
                session.add(brand)
                session.flush()
                fragrance = Fragrance(
                    brand_id=brand.id,
                    name=f"Export Test Fragrance {suffix}",
                    slug=f"export-test-{suffix}",
                )
                session.add(fragrance)
                session.flush()
                variant = ProductVariant(
                    fragrance_id=fragrance.id,
                    concentration="EDP",
                    size_ml=Decimal("100"),
                    canonical_key=f"baseline-test|{suffix}|edp|100|standard",
                )
                session.add(variant)
                session.flush()
                offer = Offer(
                    store_id=store.id,
                    product_variant_id=variant.id,
                    external_product_id=f"phase0-export-{suffix}",
                    url="https://www.notino.fr/test/phase0-export/",
                    price=Decimal("42.50"),
                    currency="EUR",
                    availability="in_stock",
                    source="ci_fixture",
                    confidence=Decimal("0.990"),
                    captured_at=datetime.now(timezone.utc),
                    valid_until=datetime.now(timezone.utc) + timedelta(hours=1),
                    status="active",
                )
                session.add(offer)
                session.commit()
                expected_offer_id = offer.id

            _export_store_chunk(store.slug, str(chunk), result_queue)
            result = result_queue.get(timeout=5)
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["offers_read"], 1)
            with chunk.open(newline="", encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(len(rows), 1)
            row = rows[0]
            self.assertEqual(row["store"], store.slug)
            self.assertEqual(row["external_product_id"], f"phase0-export-{suffix}")
            self.assertEqual(row["canonical_product_id"], str(fragrance.id))
            self.assertEqual(row["brand"], brand.name)
            self.assertEqual(row["fragrance"], fragrance.name)
            self.assertEqual(row["concentration"], "EDP")
            self.assertEqual(row["size_ml"], "100.0000")
            self.assertEqual(row["offer_url"], "https://www.notino.fr/test/phase0-export/")
            self.assertEqual(row["price"], "42.50")
            self.assertEqual(row["currency"], "EUR")
            self.assertEqual(row["availability"], "in_stock")
            self.assertEqual(row["match_status"], "matched")
            self.assertEqual(row["is_valid_offer"], "true")
            self.assertEqual(row["source"], "ci_fixture")
        finally:
            with Session(engine) as session:
                if offer is not None:
                    persisted = session.get(Offer, offer.id)
                    if persisted is not None:
                        session.delete(persisted)
                if store is not None:
                    persisted = session.get(Store, store.id)
                    if persisted is not None:
                        session.delete(persisted)
                if variant is not None:
                    persisted = session.get(ProductVariant, variant.id)
                    if persisted is not None:
                        session.delete(persisted)
                if fragrance is not None:
                    persisted = session.get(Fragrance, fragrance.id)
                    if persisted is not None:
                        session.delete(persisted)
                if brand is not None:
                    persisted = session.get(Brand, brand.id)
                    if persisted is not None:
                        session.delete(persisted)
                session.commit()
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
