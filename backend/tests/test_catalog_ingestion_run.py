from __future__ import annotations

import unittest
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Store, IngestionRun
from app.repositories.ingestion_runs import (
    finish_ingestion_run,
    record_ingestion_progress,
    start_ingestion_run,
)


class IngestionRunLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.store = Store(
            name="Fixture Store",
            slug="fixture-store",
            currency="EUR",
            status="active",
        )
        self.session.add(self.store)
        self.session.flush()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_run_tracks_progress_and_finishes(self) -> None:
        run_id = start_ingestion_run(self.session, store_id=self.store.id)
        record_ingestion_progress(
            self.session,
            run_id=run_id,
            products_discovered=12,
            offers_created=3,
            offers_updated=2,
            offers_rejected=1,
            error="one product could not be parsed",
        )
        finish_ingestion_run(self.session, run_id=run_id, status="partial")

        row = self.session.get(IngestionRun, run_id)
        self.assertEqual(row.status, "partial")
        self.assertIsNotNone(row.finished_at)
        self.assertEqual(row.products_discovered, 12)
        self.assertEqual(row.offers_created, 3)
        self.assertEqual(row.offers_updated, 2)
        self.assertEqual(row.offers_rejected, 1)
        self.assertEqual(row.errors, ["one product could not be parsed"])

    def test_unknown_store_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown store_id"):
            start_ingestion_run(self.session, store_id=uuid4())

    def test_negative_or_boolean_counter_is_rejected(self) -> None:
        run_id = start_ingestion_run(self.session, store_id=self.store.id)
        for value in (-1, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    record_ingestion_progress(
                        self.session, run_id=run_id, products_discovered=value
                    )

    def test_terminal_run_cannot_be_updated_or_finished_twice(self) -> None:
        run_id = start_ingestion_run(self.session, store_id=self.store.id)
        finish_ingestion_run(self.session, run_id=run_id)
        with self.assertRaisesRegex(ValueError, "cannot update"):
            record_ingestion_progress(
                self.session, run_id=run_id, products_discovered=1
            )
        with self.assertRaisesRegex(ValueError, "cannot finish"):
            finish_ingestion_run(self.session, run_id=run_id)

    def test_errors_are_bounded_to_latest_one_hundred(self) -> None:
        run_id = start_ingestion_run(self.session, store_id=self.store.id)
        for index in range(105):
            record_ingestion_progress(
                self.session, run_id=run_id, error=f"error-{index}"
            )
        row = self.session.get(IngestionRun, run_id)
        self.assertEqual(len(row.errors), 100)
        self.assertEqual(row.errors[0], "error-5")
        self.assertEqual(row.errors[-1], "error-104")


if __name__ == "__main__":
    unittest.main()
