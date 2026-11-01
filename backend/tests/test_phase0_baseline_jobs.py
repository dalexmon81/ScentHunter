from __future__ import annotations

import csv
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

    def test_csv_is_written_to_volume_path_and_published_atomically(self):
        conn = connect()
        try:
            conn.execute(
                """INSERT INTO store_products
                   (store,url,name,brand,sku,gtin,size_ml,concentration,price,
                    currency,availability,fetched_at)
                   VALUES('bplatz','https://shop.test/p','Fragrance 100 ml',
                          'Brand','SKU-1','',100,'Eau de Parfum',80,'EUR',
                          'in_stock',1793538000)"""
            )
            conn.commit()
        finally:
            conn.close()

        catalog = CatalogRepository(
            [
                CanonicalProduct(
                    product_id="product-1",
                    brand="Brand",
                    name="Fragrance",
                    variants=(CanonicalVariant("variant-1", 100, "100 ml"),),
                    concentration="Eau de Parfum",
                )
            ],
            self.root / "product_catalog.json",
        )
        output = self.root / "phase0" / "baseline" / "job-1.csv"
        job = {"id": "job-1", "output_path": str(output)}
        with patch(
            "scenthunter_next_engine.catalog_repository.CatalogRepository.from_file",
            return_value=catalog,
        ):
            result = generate_csv(job, "test-worker")

        self.assertEqual(result["rows_written"], 1)
        self.assertTrue(output.is_file())
        self.assertFalse(output.with_suffix(".csv.tmp").exists())
        with output.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            self.assertEqual(reader.fieldnames, list(COLUMNS))
            rows = list(reader)
        offer_rows = [row for row in rows if row.get("source")]
        status_rows = {row["store"]: row["store_status"] for row in rows}
        self.assertEqual(len(offer_rows), 1)
        self.assertEqual(offer_rows[0]["store"], "bplatz")
        self.assertEqual(offer_rows[0]["canonical_product_id"], "product-1")
        self.assertEqual(offer_rows[0]["match_status"], "matched")
        self.assertEqual(offer_rows[0]["catalog_product_count"], "1")
        self.assertEqual(offer_rows[0]["is_valid_offer"], "true")
        self.assertEqual(len(STORES), 9)
        self.assertEqual(set(status_rows), set(STORES))
        self.assertTrue(all(status == "completed" for status in status_rows.values()))


if __name__ == "__main__":
    unittest.main()
