from datetime import datetime, timedelta, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.models import Base, NotinoFeedListing
from app.services.notino_affiliate import is_valid_notino_affiliate_url
from app.services.notino_feed_listings import refresh_notino_listings
from app.services.notino_phase2_search import search_notino_retailer_listings
from product_matcher import ProductMatcher
from scripts.import_notino_phase2_persistent import _audit_feed_rows, _duplicate_valid_feed_gtins
from main import _aggregate_identity_results, _resolve_offer_identity, _merge_notino_phase2_offers
from scrapers.notino.affiliate_feed import _product_url
import main
from scripts.select_notino_retailer_only_sample import find_publicable_sample


def affiliate(destination):
    from urllib.parse import quote
    return "https://www.kqzyfj.com/click-123-456?url=" + quote(destination, safe="")


def row(external_id, title, destination):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "id": external_id, "brand": "Rasasi", "title": title,
        "link": affiliate(destination), "last_updated": now,
        "availability": "in stock", "price": "29.90 EUR", "size": "100 ml",
    }


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
    def test_retailer_only_sample_selector_skips_rows_rejected_by_public_guards(self):
        candidates = [
            ("Vivian Gray", "Love Bomb Eau de Toilette 10 ml", "BLOCKED"),
            ("Example", "Night Eau de Parfum 100 ml", "PUBLISHABLE"),
        ]

        def lookup(query):
            if "Love Bomb" in query:
                return [{"external_id": "BLOCKED"}]
            return [{"external_id": "PUBLISHABLE"}]

        selected = find_publicable_sample(
            candidates,
            lookup,
            lambda offer: offer["external_id"] == "PUBLISHABLE",
        )

        self.assertEqual(
            selected,
            ("Example", "Night Eau de Parfum 100 ml", "PUBLISHABLE"),
        )

    def test_watchdog_does_not_finalize_a_worker_that_is_still_running(self):
        job_id = "watchdog-test"
        cancel_event = main.threading.Event()
        done_event = main.threading.Event()
        job = {
            "job_id": job_id,
            "query": "unregistered test query",
            "started_at": main.time.time() - 25,
            "completed": False,
            "status": "searching",
            "cancel_event": cancel_event,
            "done_event": done_event,
            "errors": {},
            "stores": {},
            "results": [],
            "offers": [],
        }
        with patch.object(main, "JOB_TIMEOUT_SECONDS", 1):
            with main.JOBS_LOCK:
                main.JOBS[job_id] = job
            try:
                snapshot = main._snapshot(job_id)
            finally:
                with main.JOBS_LOCK:
                    main.JOBS.pop(job_id, None)

        self.assertFalse(snapshot["completed"])
        self.assertEqual(snapshot["status"], "timed_out")
        self.assertTrue(cancel_event.is_set())
        self.assertFalse(done_event.is_set())

    def test_public_search_can_run_only_the_requested_retailer(self):
        class FakeThread:
            def __init__(self, *, target, args, **kwargs):
                self.target = target
                self.args = args
                self.kwargs = kwargs

            def start(self):
                return None

        with (
            patch.object(main, "_CATALOG_BOOTSTRAP_RUNNING", False),
            patch.object(main, "_CATALOG_BOOTSTRAP_DONE", True),
            patch.object(main, "_CATALOG_BOOTSTRAP_ERROR", None),
            patch.object(main, "_cancel_active_jobs", return_value=True),
            patch.object(main, "_snapshot", side_effect=lambda job_id: {"job_id": job_id}),
            patch.object(main.threading, "Thread", FakeThread),
        ):
            result = main.search_start(q="Lattafa", store="notino")
        try:
            self.assertEqual(main.JOBS[result["job_id"]]["requested_stores"], ["notino"])
        finally:
            main.JOBS.pop(result["job_id"], None)

    def test_public_phase2_search_does_not_run_legacy_matcher_on_retailer_only_rows(self):
        retailer_listing = {
            "catalog_id": "notino-feed-sample",
            "external_id": "RETAIL_ONLY",
            "brand": "Example",
            "name": "Example Night Eau de Parfum 100 ml",
            "store": "notino",
            "price": 25.41,
            "price_num": 25.41,
            "currency": "EUR",
            "url": feed_row()["link"],
            "availability": "in_stock",
            "source": "cj_notino_fr_feed",
            "_match_status": "notino_retailer_only",
        }
        notino_report = {
            "store": "notino",
            "status": "no_match",
            "verified": True,
            "count": 0,
            "results": [],
            "details": {},
        }
        with (
            patch.dict("os.environ", {"NOTINO_CJ_STANDALONE_ENABLED": "1"}),
            patch.object(main, "CATALOG_ENGINE_AVAILABLE", True),
            patch.object(main, "catalog_search_local", lambda *_args, **_kwargs: []),
            patch(
                "app.services.notino_phase2_search.search_notino_phase2",
                return_value=[],
            ),
            patch(
                "app.services.notino_phase2_search.search_notino_retailer_listings",
                return_value=[retailer_listing],
            ),
            patch.object(
                main, "_collect_catalog_reports_isolated", return_value=[notino_report],
            ),
            patch.object(
                main,
                "_resolve_offer_identity",
                side_effect=AssertionError("legacy matcher must not see retailer-only rows"),
            ),
        ):
            reports = main.collect_store_reports_isolated("Example", ["notino"])

        report = next(item for item in reports if item["store"] == "notino")
        # A feed-only price is not publishable until the matching Notino
        # product page has been hydrated in the background.
        self.assertEqual(report["results"], [])
        self.assertEqual(report["status"], "success")

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
            self.assertEqual(public["availability"], "in_stock")
            self.assertTrue(public["available"])
            self.assertTrue(public["in_stock"])
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
        image_warning = feed_row("IMAGE")
        image_warning["image_link"] = "http://not-secure.example/image.jpg"
        audit = _audit_feed_rows([
            feed_row("GOOD"),
            feed_row("BAD", link="https://notino.fr/example"),
            image_warning,
        ])
        self.assertEqual(audit["accepted_listings"], 2)
        self.assertEqual(audit["accepted_brand_count"], 1)
        self.assertEqual(
            audit["rejected"],
            {"invalid_affiliate_url": 1, "invalid_image_url": 1},
        )

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


class NotinoHawasRegressionTests(unittest.TestCase):
    def test_affiliate_clickout_must_resolve_to_a_notino_product_detail(self):
        self.assertTrue(is_valid_notino_affiliate_url(affiliate(
            "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/"
        )))
        self.assertFalse(is_valid_notino_affiliate_url(affiliate(
            "https://www.notino.fr/rasasi/hawas-ice/"
        )))
        self.assertFalse(is_valid_notino_affiliate_url(affiliate(
            "https://www.notino.fr/search/?q=hawas+ice"
        )))

    def test_cj_parser_rejects_generic_hawas_ice_page(self):
        self.assertEqual(
            _product_url("https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/"),
            "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/",
        )
        self.assertIsNone(_product_url("https://www.notino.fr/rasasi/hawas-ice/"))

    def test_hawas_ice_single_and_gift_set_are_not_mixed(self):
        single = affiliate(
            "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/"
        )
        gift = affiliate(
            "https://www.notino.fr/rasasi/hawas-ice-coffret-cadeau-pour-homme/p-17770001/"
        )
        self.assertTrue(is_valid_notino_affiliate_url(single))
        self.assertTrue(is_valid_notino_affiliate_url(gift))
        # The URL validator establishes a product-detail destination; the
        # existing bundle guard must still reject gift sets from perfume cards.
        from product_matcher import ProductMatcher
        self.assertTrue(ProductMatcher._is_non_fragrance_offer({
            "name": "Rasasi Hawas Ice",
            "brand": "Rasasi",
            "url": gift,
        }))
        self.assertFalse(ProductMatcher._is_non_fragrance_offer({
            "name": "Rasasi Hawas Ice Eau de Parfum 100 ml",
            "brand": "Rasasi",
            "url": single,
        }))

    def test_hawas_line_editions_remain_separate_retailer_listings(self):
        rows = [
            row("HAWAS-ICE", "Hawas Ice Eau de Parfum 100 ml",
                "https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum/p-16242201/"),
            row("HAWAS-ELIXIR", "Hawas Elixir Eau de Parfum 100 ml",
                "https://www.notino.fr/rasasi/hawas-elixir-eau-de-parfum/p-17770002/"),
            row("HAWAS-LA-MER", "Hawas La Mer Eau de Parfum 100 ml",
                "https://www.notino.fr/rasasi/hawas-la-mer-eau-de-parfum/p-17770003/"),
            row("HAWAS-MAJESTIC", "Hawas Majestic Eau de Parfum 100 ml",
                "https://www.notino.fr/rasasi/hawas-majestic-eau-de-parfum/p-17770004/"),
        ]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notino.sqlite"
            engine = create_engine(f"sqlite:///{path}")
            Base.metadata.create_all(engine)
            now = datetime.now(timezone.utc)
            with Session(engine) as session, session.begin():
                result = refresh_notino_listings(session, rows, now)
                self.assertEqual(result["listings"], 4)
            with patch.dict("os.environ", {"NOTINO_PHASE2_DATABASE": str(path)}):
                found = search_notino_retailer_listings("Rasasi Hawas", set())
            self.assertEqual({item["external_id"] for item in found}, {
                "HAWAS-ICE", "HAWAS-ELIXIR", "HAWAS-LA-MER", "HAWAS-MAJESTIC",
            })
            self.assertEqual(len({item["url"] for item in found}), 4)
            engine.dispose()


    def test_phase2_uses_hydrated_price_and_collapses_same_notino_product_page(self):
        feed = {
            "store": "notino", "shop": "notino", "source": "cj_notino_fr_feed",
            "external_id": "HAWAS-DIVA", "gtin": "614514331088",
            "name": "Rasasi Hawas Diva Eau de Parfum 100 ml",
            "size_ml": 100, "variant": "EDP", "price": 26.77,
            "price_num": 26.77, "currency": "EUR",
            "url": affiliate("https://www.notino.fr/rasasi/hawas-diva-eau-de-parfum-pour-femme/p-16337384/"),
            "_match_status": "notino_retailer_only",
        }
        hydrated = {
            "store": "notino", "shop": "notino",
            "name": "Rasasi Hawas Diva Eau de Parfum 100 ml",
            "size_ml": 100, "concentration": "EDP", "price": "25.50 €",
            "price_num": 25.50, "currency": "EUR", "available": True,
            "availability": "in_stock", "in_stock": True,
            "fetched_at": 1794590000,
            "url": "https://www.notino.fr/rasasi/hawas-diva-eau-de-parfum-pour-femme/p-16337384/",
        }
        result = _merge_notino_phase2_offers([feed], [hydrated])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["price_num"], 25.50)
        self.assertEqual(result[0]["price_source"], "notino_product_page_hydration")
        self.assertEqual(result[0]["external_id"], "HAWAS-DIVA")
        self.assertEqual(result[0]["gtin"], "614514331088")
        self.assertEqual(result[0]["url"], feed["url"])

    def test_phase2_does_not_publish_unhydrated_feed_price(self):
        feed = {
            "store": "notino", "source": "cj_notino_fr_feed",
            "name": "Rasasi Hawas Ice Eau de Parfum 100 ml",
            "size_ml": 100, "price": 36.00, "price_num": 36.00,
            "url": affiliate("https://www.notino.fr/rasasi/hawas-ice-eau-de-parfum-pour-homme/p-16242201/"),
        }
        self.assertEqual(_merge_notino_phase2_offers([feed], []), [])

    def test_phase2_keeps_hawas_editions_on_distinct_product_ids(self):
        feed = [
            {"store": "notino", "name": "Hawas Ice 100 ml", "size_ml": 100,
             "url": affiliate("https://www.notino.fr/rasasi/hawas-ice/p-16242201/")},
            {"store": "notino", "name": "Hawas Elixir 100 ml", "size_ml": 100,
             "url": affiliate("https://www.notino.fr/rasasi/hawas-elixir/p-16306315/")},
        ]
        hydrated = [
            {"store": "notino", "name": "Hawas Ice 100 ml", "size_ml": 100,
             "price_num": 24.90, "price": "24.90 €", "url": "https://www.notino.fr/rasasi/hawas-ice/p-16242201/"},
            {"store": "notino", "name": "Hawas Elixir 100 ml", "size_ml": 100,
             "price_num": 23.90, "price": "23.90 €", "url": "https://www.notino.fr/rasasi/hawas-elixir/p-16306315/"},
        ]
        result = _merge_notino_phase2_offers(feed, hydrated)
        self.assertEqual(len(result), 2)
        self.assertEqual({item["price_num"] for item in result}, {24.90, 23.90})
        self.assertEqual(len({item["url"] for item in result}), 2)



    def test_feed_search_hides_price_until_background_page_hydration_is_done(self):
        import sqlite3
        import time
        from scrapers.notino.affiliate_feed import search_feed
        import catalog_engine

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.executescript("""
            CREATE TABLE store_product_variants (
                store TEXT, url TEXT, variant_key TEXT, name TEXT, brand TEXT,
                image TEXT, sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL,
                concentration TEXT, gender TEXT, price REAL, currency TEXT,
                availability TEXT, fetched_at REAL, variant_url TEXT,
                regular_price REAL, coupon_code TEXT, coupon_required INTEGER
            );
            CREATE TABLE store_urls (store TEXT, url TEXT, active INTEGER);
            CREATE TABLE hydration_queue (
                store TEXT, url TEXT, state TEXT, last_error TEXT, first_seen_at REAL
            );
            CREATE TABLE store_products (
                store TEXT, url TEXT, fetch_status TEXT, price REAL, fetched_at REAL
            );
        """)
        now = time.time()
        url = "https://www.notino.fr/rasasi/hawas-diva/p-16337384/"
        conn.execute(
            "INSERT INTO store_product_variants VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("notino", url, "100ml:614514331088", "Rasasi Hawas Diva 100 ml",
             "Rasasi", "", "", "614514331088", "", 100, "EDP", "women",
             26.77, "EUR", "in_stock", now, url, 31.50, None, 0),
        )
        conn.execute("INSERT INTO store_urls VALUES(?,?,1)", ("notino", url))
        conn.execute(
            "INSERT INTO hydration_queue VALUES(?,?,?,?,?)",
            ("notino", url, "PENDING", None, now - 60),
        )
        conn.execute(
            "INSERT INTO store_products VALUES(?,?,?,?,?)",
            ("notino", url, "OK", None, now),
        )
        conn.commit()
        with patch.object(catalog_engine, "db", return_value=conn):
            self.assertEqual(search_feed("Hawas Diva")["results"], [])
            conn.execute(
                "UPDATE hydration_queue SET state='DONE' WHERE store='notino' AND url=?",
                (url,),
            )
            conn.execute(
                "UPDATE store_product_variants SET price=25.50, fetched_at=? WHERE store='notino' AND url=?",
                (now + 1, url),
            )
            conn.execute(
                "UPDATE store_products SET price=25.50, fetched_at=? WHERE store='notino' AND url=?",
                (now + 1, url),
            )
            conn.commit()
            result = search_feed("Hawas Diva")
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["price_num"], 25.50)
        conn.close()



if __name__ == "__main__":
    unittest.main()
