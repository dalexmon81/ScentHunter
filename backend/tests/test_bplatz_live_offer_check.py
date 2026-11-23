from __future__ import annotations

import json
import os
import shlex
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))

from catalog_engine import parse_product  # noqa: E402
from scrapers.bplatz.scraper import parse_product_html  # noqa: E402
from scripts.check_bplatz_liquid_brun_live import build_report  # noqa: E402
from scripts.persist_bplatz_phase2_live_offer import _validate_report  # noqa: E402
from scripts import persist_bplatz_liquid_brun_live as writer  # noqa: E402


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
        self.assertTrue(report["raw_record"]["currency_explicit"])
        self.assertEqual(report["raw_record"]["product_url"], report["url"])
        self.assertFalse(report["database_written"])

    def test_out_of_stock_is_a_verified_observation_but_not_publishable(self):
        page, worker_item = self.parsed_fixture()
        page["availability"] = "out_of_stock"
        worker_item["availability"] = "out_of_stock"
        worker_item["available"] = False
        report = build_report(page, worker_item, datetime.now(timezone.utc))
        self.assertEqual(report["status"], "unavailable")
        self.assertEqual(report["availability"], "out_of_stock")
        self.assertFalse(report["publication_eligible"])
        self.assertFalse(report["database_written"])

    def test_disagreeing_stock_parsers_are_rejected(self):
        page, worker_item = self.parsed_fixture()
        page["availability"] = "out_of_stock"
        with self.assertRaisesRegex(RuntimeError, "disagree on availability"):
            build_report(page, worker_item, datetime.now(timezone.utc))

    def test_defaulted_currency_is_not_accepted_as_evidence(self):
        page, worker_item = self.parsed_fixture()
        worker_item["currency_explicit"] = False
        with self.assertRaisesRegex(RuntimeError, "explicit currency"):
            build_report(page, worker_item, datetime.now(timezone.utc))

    def test_persistence_rejects_stale_or_different_canonical_variant(self):
        page, worker_item = self.parsed_fixture()
        report = build_report(page, worker_item, datetime.now(timezone.utc))
        stale = dict(report, captured_at="2026-01-01T00:00:00+00:00")
        with self.assertRaisesRegex(ValueError, "one-hour"):
            _validate_report(stale, now=datetime.now(timezone.utc))

        wrong_variant = dict(report, canonical_variant_id="another-variant")
        with self.assertRaisesRegex(ValueError, "authorized Liquid Brun pilot"):
            _validate_report(wrong_variant, now=datetime.now(timezone.utc))

    def test_api_verification_compares_prices_numerically(self):
        report = {"url": self.url, "price": "27.5"}
        search = Mock()
        search.json.return_value = {
            "status": "completed", "count": 1,
            "results": [{"offers": [{
                "store": "Bplatz", "availability": "in_stock", "currency": "EUR",
                "url": self.url, "price": "27.50",
            }]}],
        }
        status = Mock()
        status.json.return_value = {"status": "ready", "published_offers": 1}
        with patch.object(writer.requests, "get", side_effect=[search, status]):
            self.assertEqual(writer.verify_public_api(report)["search"]["count"], 1)

    def test_remote_writer_runs_in_a_shell(self):
        report = {"url": self.url, "price": "27.5"}
        env = {
            "CONFIRM_PRODUCTION_WRITE": "true", "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ID": "12345",
        }
        with patch.dict(os.environ, env), \
             patch.object(writer, "fetch_live_offer", return_value=report), \
             patch.object(writer, "verify_public_api", return_value={}), \
             patch.object(writer.subprocess, "run") as run:
            self.assertEqual(writer.main(), 0)
        command = shlex.split(run.call_args.args[0][-1])
        self.assertEqual(command[:2], ["/bin/sh", "-lc"])
        self.assertIn("scripts/persist_bplatz_phase2_live_offer.py", command[2])
