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
import main
from main import _aggregate_identity_results


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
            self.assertEqual(offers[0]["gtin"], "4006381333931")
            groups, unresolved = _aggregate_identity_results(offers)
            self.assertEqual(unresolved, [])
            self.assertTrue(groups[0]["retailer_only"])
            public = groups[0]["offers"][0]
            self.assertEqual(public["price_num"], 25.41)
            self.assertEqual(public["url"], feed_row()["link"])
            self.assertFalse(public["price_stale"])
            engine.dispose()

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
                feed_row("BAD-SALE", sale_price="19 USD"),
                feed_row("INVALID-SALE", sale_price="invalid"),
                feed_row("HIGH-SALE", sale_price="35 EUR"),
            ], now)
            self.assertEqual(stats, {
                "listings": 1,
                "rejected": {"invalid_affiliate_url": 1, "invalid_sale_price": 3},
            })
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

    def test_registered_family_keeps_safe_listing_and_rejects_conflicting_size(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notino.sqlite"
            engine = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(engine)
            now = datetime.now(timezone.utc)
            rows = [
                feed_row(
                    str(size), brand="French Avenue",
                    title=f"French Avenue Liquid Brun Limited Edition Extrait de Parfum {size} ml",
                    size=f"{size} ml", last_updated=now.isoformat(),
                )
                for size in (100, 150)
            ]
            with Session(engine) as session, session.begin():
                refresh_notino_listings(session, rows, now)
            with (
                patch.dict("os.environ", {
                    "NOTINO_PHASE2_DATABASE": str(path),
                    "NOTINO_CJ_STANDALONE_ENABLED": "1",
                }),
                patch.object(main, "CATALOG_ENGINE_AVAILABLE", True),
                patch.object(main, "catalog_search_local", return_value=[]),
                patch.object(main, "_collect_catalog_reports_isolated", return_value=[]),
            ):
                reports = main.collect_store_reports_isolated(
                    "Liquid Brun Limited Edition", ["notino"],
                )
            offers = reports[0]["results"]
            self.assertEqual(len(offers), 1)
            self.assertEqual(offers[0]["size_ml"], 150)
            self.assertEqual(offers[0]["_match_status"], "notino_retailer_only")
            self.assertEqual(offers[0]["url"], rows[1]["link"])
            engine.dispose()

    def test_family_score_alone_does_not_merge_different_concentrations(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notino.sqlite"
            engine = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(engine)
            now = datetime.now(timezone.utc)
            rows = [
                feed_row(
                    external_id, brand="DIOR", title=title, gtin="",
                    last_updated=now.isoformat(),
                    link=f"https://www.kqzyfj.com/click-1-2?url=https%3A%2F%2Fwww.notino.fr%2Fdior%2F{slug}%2Fp-{product_id}%2F",
                )
                for external_id, title, slug, product_id in (
                    ("EDT", "DIOR Sauvage Eau de Toilette 100 ml", "sauvage-toilette", 123),
                    ("ELIXIR", "DIOR Sauvage Elixir extrait de parfum 100 ml", "sauvage-elixir", 456),
                )
            ]
            with Session(engine) as session, session.begin():
                refresh_notino_listings(session, rows, now)
            with (
                patch.dict("os.environ", {
                    "NOTINO_PHASE2_DATABASE": str(path),
                    "NOTINO_CJ_STANDALONE_ENABLED": "1",
                }),
                patch.object(main, "CATALOG_ENGINE_AVAILABLE", True),
                patch.object(main, "catalog_search_local", return_value=[]),
                patch.object(main, "_collect_catalog_reports_isolated", return_value=[]),
            ):
                reports = main.collect_store_reports_isolated("Dior Sauvage", ["notino"])
            offers = main.dedupe_results(reports[0]["results"])
            groups, _ = _aggregate_identity_results(offers)
            self.assertEqual(len(groups), 2)
            self.assertTrue(all(offer["_match_status"] == "notino_retailer_only" for offer in offers))
            engine.dispose()


if __name__ == "__main__":
    unittest.main()
