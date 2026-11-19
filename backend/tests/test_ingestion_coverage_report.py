from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, IngestionRaw, IngestionRun, Offer, Store
from scripts.ingestion_coverage_report import build_report


class IngestionCoverageReportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.since = datetime.now(timezone.utc) - timedelta(days=1)
        self.notino = Store(
            name="Notino.fr", slug="notino-fr", domain="notino.fr",
            country="FR", currency="EUR", status="active",
        )
        self.deloox = Store(
            name="Deloox.be", slug="deloox-be", domain="www.deloox.be",
            country="BE", currency="EUR", status="active",
        )
        self.session.add_all([self.notino, self.deloox])
        self.session.flush()
        self.session.add(IngestionRun(
            store_id=self.notino.id, status="completed",
            started_at=datetime.now(timezone.utc),
            products_discovered=120, offers_created=4,
            offers_updated=2, offers_rejected=3, errors=[],
        ))
        self.session.add_all([
            IngestionRaw(
                store_id=self.notino.id, raw_payload={},
                external_product_id="x1", status="unmatched",
                rejection_reason="no_canonical_variant_match",
            ),
            IngestionRaw(
                store_id=self.notino.id, raw_payload={},
                external_product_id="x2", status="pending",
                rejection_reason="currency_not_explicit_in_source",
            ),
        ])
        self.session.add(Offer(
            store_id=self.notino.id, external_product_id="x3",
            url="https://www.notino.fr/p/x3", price="39.00",
            currency="EUR", availability="in_stock",
            source="fixture", status="active",
        ))
        self.session.commit()

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_report_distinguishes_no_run_from_empty_discovery(self):
        report = build_report(self.session, since=self.since)
        rows = {row["store"]: row for row in report["stores"]}
        self.assertEqual(rows["notino-fr"]["runs"], 1)
        self.assertEqual(rows["notino-fr"]["products_discovered"], 120)
        self.assertEqual(rows["notino-fr"]["offers_created"], 4)
        self.assertEqual(rows["notino-fr"]["staged_rows_by_status"], {
            "pending": 1, "unmatched": 1,
        })
        self.assertEqual(
            rows["notino-fr"]["top_unresolved_reasons"][0]["reason"],
            "currency_not_explicit_in_source",
        )
        self.assertEqual(rows["deloox-be"]["runs"], 0)
        self.assertIsNone(rows["deloox-be"]["latest_run"])
        self.assertEqual(report["totals"]["stores_with_runs"], 1)
        self.assertEqual(report["totals"]["active_offers_in_database"], 1)


if __name__ == "__main__":
    unittest.main()
