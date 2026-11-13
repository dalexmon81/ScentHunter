from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, NotinoFeedListing
from app.services.notino_feed_listings import refresh_notino_listings
from app.services.notino_phase2_search import search_notino_retailer_listings
from product_matcher import ProductMatcher
from scripts.import_notino_phase2_persistent import _audit_feed_rows, _duplicate_valid_feed_gtins
from main import _aggregate_identity_results, _resolve_offer_identity
import main


def feed_row(external_id="ONE", **changes):
    row = {
        "id": external_id, "brand": "Example", "title": "Example Night Eau de Parfum 100 ml",
        "size": "100 ml", "gtin": "4006381333931", "price": "29.90 EUR",
        "sale_price": "25.41 EUR", "availability": "in stock",
        "link": "https://www.kqzyfj.com/click-1-2?url=https%3A%2F%2Fwww.notino.fr%2Fexample%2Fnight%2Fp-123%2F",
        "last_updated": "2026-11-11T03:04:42-08:00",
    }
    row.update(changes)
    return row


class NotinoRetailerListingTests(unittest.TestCase):
    def test_snapshot_search_and_public_api_keep_price_and_tracking(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notino.sqlite"
            engine = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(engine)
            now = datetime.now(timezone.utc)
            with Session(engine) as session, session.begin():
                stats = refresh_notino_listings(
                    session, [feed_row(last_updated=now.isoformat())], now,
                )
                self.assertEqual(stats["listings"], 1)
            with patch.dict("os.environ", {"NOTINO_PHASE2_DATABASE": str(path)}):
                offers = search_notino_retailer_listings("Example Night", set())
                self.assertEqual(search_notino_retailer_listings("%", set()), [])
                self.assertEqual(search_notino_retailer_listings("Example Night", {"ONE"}), [])
            self.assertEqual(len(offers), 1)
            groups, unresolved = _aggregate_identity_results(offers)
            self.assertEqual(unresolved, [])
            self.assertTrue(groups[0]["retailer_only"])
            public = groups[0]["offers"][0]
            self.assertEqual(public["price_num"], 25.41)
            self.assertEqual(public["url"], feed_row()["link"])
            self.assertFalse(public["price_stale"])
            engine.dispose()

    def test_retailer_only_feed_rows_cannot_be_fuzzy_promoted(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notino.sqlite"
            engine = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(engine)
            now = datetime.now(timezone.utc)
            with Session(engine) as session, session.begin():
                refresh_notino_listings(
                    session, [feed_row(last_updated=now.isoformat())], now,
                )
            with patch.dict("os.environ", {"NOTINO_PHASE2_DATABASE": str(path)}):
                offers = search_notino_retailer_listings("Example Night", set())
            self.assertEqual(len(offers), 1)
            self.assertEqual(offers[0]["_match_policy"], "exact_gtin_only")
            matcher = ProductMatcher([])
            self.assertIsNone(matcher.match(offers[0], "Example Night"))
            with patch.object(main, "PRODUCT_MATCHER", matcher):
                resolved = _resolve_offer_identity(offers[0], "Example Night")
            self.assertNotEqual(resolved.get("_match_status"), "matched")
            self.assertIsNone(resolved.get("catalog_id"))
            engine.dispose()

    def test_read_only_snapshot_audit_reports_acceptance_and_rejections(self):
        audit = _audit_feed_rows([
            feed_row("GOOD"),
            feed_row("BAD", link="https://notino.fr/example"),
        ])
        self.assertEqual(audit["accepted_listings"], 1)
        self.assertEqual(audit["accepted_brand_count"], 1)
        self.assertEqual(audit["rejected"], {"invalid_affiliate_url": 1})

    def test_duplicate_valid_feed_gtins_are_held_for_retailer_only_publication(self):
        rows = [
            feed_row("FIRST"),
            feed_row("SECOND"),
            feed_row("THIRD", gtin="invalid"),
        ]
        self.assertEqual(
            _duplicate_valid_feed_gtins(rows),
            {"4006381333931"},
        )

    def test_refresh_replaces_old_snapshot_and_keeps_rejected_rows_out(self):
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(engine)
        now = datetime.now(timezone.utc)
        with Session(engine) as session, session.begin():
            refresh_notino_listings(session, [feed_row()], now)
        with Session(engine) as session, session.begin():
            stats = refresh_notino_listings(session, [
                feed_row("TWO", availability="out of stock"),
                feed_row("BAD", link="https://notino.fr/example"),
            ], now)
            self.assertEqual(stats, {"listings": 1, "rejected": {"invalid_affiliate_url": 1}})
        with Session(engine) as session:
            self.assertEqual([x.external_id for x in session.scalars(select(NotinoFeedListing))], ["TWO"])
        with Session(engine) as session, session.begin():
            with self.assertRaises(ValueError):
                refresh_notino_listings(session, [feed_row(link="https://notino.fr/example")], now)
        with Session(engine) as session:
            self.assertEqual([x.external_id for x in session.scalars(select(NotinoFeedListing))], ["TWO"])
        with Session(engine) as session, session.begin():
            with self.assertRaisesRegex(ValueError, "snapshot_older"):
                refresh_notino_listings(session, [
                    feed_row("TWO", last_updated="2026-11-10T00:00:00Z"),
                ], now)
        with Session(engine) as session:
            self.assertEqual([x.external_id for x in session.scalars(select(NotinoFeedListing))], ["TWO"])
        engine.dispose()

    def test_old_snapshot_is_marked_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notino.sqlite"
            engine = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(engine)
            now = datetime.now(timezone.utc)
            with Session(engine) as session, session.begin():
                refresh_notino_listings(
                    session,
                    [feed_row(last_updated=(now - timedelta(days=2)).isoformat())],
                    now,
                )
            with patch.dict("os.environ", {"NOTINO_PHASE2_DATABASE": str(path)}):
                offers = search_notino_retailer_listings("Night", set())
            self.assertTrue(_aggregate_identity_results(offers)[0][0]["offers"][0]["price_stale"])
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
