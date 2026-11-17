from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from catalog_engine import parse_product  # noqa: E402
from scrapers.bplatz.scraper import parse_product_html  # noqa: E402
from scripts.check_bplatz_liquid_brun_live import build_report  # noqa: E402


class BplatzLiveOfferCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.raw.html"
        metadata = ROOT / "tests/fixtures/bplatz/liquid-brun-54015243419916.meta.json"
        details = json.loads(metadata.read_text(encoding="utf-8"))
        cls.url = details["url_final"]
        cls.captured_at = datetime.fromisoformat(
            details["acquired_at_utc"]
        ).astimezone(timezone.utc)
        cls.html = fixture.read_bytes()

    def parsed_fixture(self):
        page = parse_product_html(
            self.html.decode("utf-8"), self.url, "French Avenue Liquid Brun"
        )
        worker_item = parse_product("bplatz", self.url, self.html)
        self.assertIsNotNone(page)
        self.assertIsNotNone(worker_item)
        return page, worker_item

    def test_fixture_resolves_to_the_expected_variant_without_database_writes(self):
        page, worker_item = self.parsed_fixture()
        report = build_report(
            page,
            worker_item,
            self.captured_at,
        )
        self.assertEqual(report["status"], "verified")
        self.assertEqual(report["canonical_product_id"], "SH-0030")
        self.assertEqual(report["canonical_variant_id"], "VAR-f87146c82d167f4c")
        self.assertEqual(report["captured_at"], self.captured_at.isoformat())
        self.assertFalse(report["database_written"])

    def test_out_of_stock_offer_fails_closed(self):
        page, worker_item = self.parsed_fixture()
        page["availability"] = "out_of_stock"
        with self.assertRaisesRegex(RuntimeError, "in-stock"):
            build_report(page, worker_item, datetime.now(timezone.utc))

    def test_defaulted_currency_is_not_accepted_as_evidence(self):
        page, worker_item = self.parsed_fixture()
        worker_item["currency_explicit"] = False
        with self.assertRaisesRegex(RuntimeError, "explicit currency"):
            build_report(page, worker_item, datetime.now(timezone.utc))
