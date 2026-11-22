from __future__ import annotations

import unittest
from unittest.mock import patch

from sqlalchemy import Column, JSON, MetaData, String, Table, create_engine, func, select
from sqlalchemy.orm import Session

from app.models import Store
from scripts.seed_postgres_fetch_queue_from_legacy_catalog import (
    STORE_CONFIG,
    _apply_candidates,
    _read_candidates,
    is_allowed_product_url,
)


class LegacyCatalogQueueSeedUrlTests(unittest.TestCase):
    def test_accepts_expected_retailer_host_and_subdomains(self):
        self.assertTrue(is_allowed_product_url(
            "https://www.deloox.be/en/product/123", "www.deloox.be"
        ))
        self.assertTrue(is_allowed_product_url(
            "https://shop.www.deloox.be/product/123", "www.deloox.be"
        ))
        self.assertFalse(is_allowed_product_url(
            "https://www.deloox.nl/product/123", "www.deloox.be"
        ))
        self.assertFalse(is_allowed_product_url(
            "https://www.deloox.lu/product/123", "www.deloox.be"
        ))


    def test_reports_rejected_urls_by_exact_hostname(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "CREATE TABLE store_urls (store TEXT, url TEXT, active INTEGER)"
                )
                connection.exec_driver_sql(
                    "INSERT INTO store_urls (store, url, active) VALUES (?, ?, ?)",
                    [
                        ("deloox", "https://www.deloox.be/product/1", 1),
                        ("deloox", "https://www.deloox.nl/product/2", 1),
                        ("deloox", "https://www.deloox.lu/product/3", 1),
                        ("deloox", "https://www.deloox.nl/product/4", 0),
                    ],
                )
                accepted, rejected, duplicates, rejected_domains = _read_candidates(connection)

            self.assertEqual(len(accepted), 1)
            self.assertEqual(rejected["deloox"], 2)
            self.assertEqual(duplicates, 0)
            self.assertEqual(rejected_domains["deloox"], {
                "www.deloox.nl": 1,
                "www.deloox.lu": 1,
            })
        finally:
            engine.dispose()

    def test_rejects_lookalike_hosts_and_unexpected_domains(self):
        self.assertFalse(is_allowed_product_url(
            "https://evildeloox.be/product/123", "www.deloox.be"
        ))
        self.assertFalse(is_allowed_product_url(
            "https://www.deloox.be.evil.example/product/123", "www.deloox.be"
        ))
        self.assertFalse(is_allowed_product_url(
            "https://www.notino.fr/product/123", "www.deloox.be"
        ))

    def test_rejects_non_http_schemes_missing_hosts_and_credentials(self):
        for url in (
            "javascript:alert(1)",
            "file:///etc/passwd",
            "/relative/product",
            "https://user:pass@www.deloox.be/product/123",
            "https:///product/123",
        ):
            with self.subTest(url=url):
                self.assertFalse(is_allowed_product_url(url, "www.deloox.be"))


class LegacyCatalogQueueSeedAtomicityTests(unittest.TestCase):
    def test_existing_store_missing_domain_is_completed(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            Store.__table__.create(engine)
            metadata = MetaData()
            Table(
                "ingestion_queue_jobs", metadata,
                Column("stage", String(24), nullable=False),
                Column("dedupe_key", String(64), nullable=False),
                Column("payload", JSON, nullable=False),
                Column("status", String(16), nullable=False),
            ).create(engine)
            store_id = __import__("uuid").uuid4()
            with engine.begin() as connection:
                with patch(
                    "scripts.seed_postgres_fetch_queue_from_legacy_catalog._queue_rows",
                    return_value=0,
                ):
                    with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
                        session.add(Store(
                            id=store_id, name="Deloox", slug="deloox-be",
                            domain=None, country=None, currency="EUR", status="active",
                        ))
                        session.commit()
                _apply_candidates(connection, [])
            with engine.connect() as connection:
                store = connection.execute(
                    select(Store.domain, Store.country).where(Store.id == store_id)
                ).one()
            self.assertEqual(store.domain, "www.deloox.be")
            self.assertEqual(store.country, "BE")
        finally:
            engine.dispose()

    def test_store_creation_rolls_back_when_queue_insert_fails(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        try:
            Store.__table__.create(engine)
            metadata = MetaData()
            Table(
                "ingestion_queue_jobs", metadata,
                Column("stage", String(24), nullable=False),
                Column("dedupe_key", String(64), nullable=False),
                Column("payload", JSON, nullable=False),
                Column("status", String(16), nullable=False),
            ).create(engine)

            with self.assertRaisesRegex(RuntimeError, "simulated queue failure"):
                with engine.begin() as connection:
                    with patch(
                        "scripts.seed_postgres_fetch_queue_from_legacy_catalog._queue_rows",
                        side_effect=RuntimeError("simulated queue failure"),
                    ):
                        _apply_candidates(connection, [])

            with engine.connect() as connection:
                remaining = connection.scalar(
                    select(func.count()).select_from(Store.__table__)
                )
            self.assertEqual(remaining, 0)

            # The savepoint release must preserve successful writes until the
            # caller commits its outer transaction.
            with engine.begin() as connection:
                inserted = _apply_candidates_with_queue_success(connection)
            self.assertEqual(inserted, 7)
            with engine.connect() as connection:
                committed = connection.scalar(
                    select(func.count()).select_from(Store.__table__)
                )
            self.assertEqual(committed, len(STORE_CONFIG))
        finally:
            engine.dispose()



def _apply_candidates_with_queue_success(connection):
    with patch(
        "scripts.seed_postgres_fetch_queue_from_legacy_catalog._queue_rows",
        return_value=7,
    ):
        return _apply_candidates(connection, [])


if __name__ == "__main__":
    unittest.main()
