"""Regression tests for Notino's authorized CJ/VIV product feed."""
import gzip
import html
import io
import zipfile
import os
import sqlite3
import tempfile
import types
import unittest
from urllib.parse import quote
from pathlib import Path
from unittest.mock import patch

from scrapers.notino import affiliate_feed as feed


SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>
 <item><g:id>LB100</g:id><g:title>French Avenue Liquid Brun Eau de Parfum 100 ml</g:title>
 <g:brand>French Avenue</g:brand><g:gtin>6291108730001</g:gtin><g:price>49,90 EUR</g:price>
 <g:availability>in stock</g:availability><g:link>https://www.notino.fr/french-avenue/liquid-brun/?utm_source=feed</g:link>
 <g:image_link>https://cdn.example.test/liquid-brun.jpg</g:image_link><g:size>100 ml</g:size></item>
 <item><g:id>LB150LE</g:id><g:title>French Avenue Liquid Brun Limited Edition 150 ml</g:title>
 <g:brand>French Avenue</g:brand><g:gtin>6291108730150</g:gtin><g:price>69.90 EUR</g:price>
 <g:availability>in stock</g:availability><g:link>https://notino.fr/french-avenue/liquid-brun-limited-edition/</g:link>
 <g:size>150 ml</g:size></item>
 <item><g:id>NO-PRICE</g:id><g:title>Invalid Eau de Parfum 100 ml</g:title><g:brand>Test</g:brand>
 <g:availability>in stock</g:availability><g:link>https://www.notino.fr/test/invalid/</g:link><g:size>100 ml</g:size></item>
 <item><g:id>FOREIGN</g:id><g:title>Foreign Eau de Parfum 100 ml</g:title><g:brand>Test</g:brand>
 <g:price>20.00 EUR</g:price><g:availability>in stock</g:availability><g:link>https://www.notino.de/test/foreign/</g:link><g:size>100 ml</g:size></item>
</channel></rss>"""


class NotinoAffiliateFeedTests(unittest.TestCase):
    def test_notino_discovery_does_not_race_the_dedicated_production_import(self):
        import catalog_engine

        class Cursor:
            def fetchone(self):
                return None

        class Connection:
            def execute(self, *_args):
                return Cursor()

            def close(self):
                pass

        with patch.object(catalog_engine, "db", return_value=Connection()), \
             patch.object(catalog_engine.importlib, "import_module") as import_module:
            result = catalog_engine.discover_store("notino")

        self.assertEqual(result["status"], "FEED_IMPORT_MANAGED_EXTERNALLY")
        self.assertEqual(result["reason"], "dedicated_notino_cj_feed_workflow")
        import_module.assert_not_called()

    def test_parses_price_size_gtin_stock_and_french_product_url(self):
        offers = feed.parse_feed(SAMPLE)
        self.assertEqual(len(offers), 2)
        by_size = {offer.size_ml: offer for offer in offers}
        self.assertEqual(by_size[100].price, 49.9)
        self.assertEqual(by_size[150].price, 69.9)
        self.assertEqual(by_size[100].gtin, "6291108730001")
        self.assertEqual(by_size[150].availability, "in_stock")
        self.assertEqual(by_size[100].url, "https://www.notino.fr/french-avenue/liquid-brun/")
        self.assertEqual(by_size[150].url, "https://www.notino.fr/french-avenue/liquid-brun-limited-edition/")
        self.assertEqual(by_size[100].image, "https://cdn.example.test/liquid-brun.jpg")

    def test_gzip_zip_and_european_price_formats(self):
        self.assertEqual(len(feed.parse_feed(gzip.compress(SAMPLE))), 2)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("NOTINO_fr-shopping.xml", SAMPLE)
        self.assertEqual(len(feed.parse_feed(buffer.getvalue())), 2)
        price, currency = feed._money("1.299,90 EUR")
        self.assertEqual(float(price), 1299.9)
        self.assertEqual(currency, "EUR")

    def test_streamed_items_report_all_links_and_reject_malformed_tail(self):
        stats = {}
        self.assertEqual(len(feed.parse_feed(SAMPLE, stats=stats)), 2)
        self.assertEqual(stats["products_read"], 4)
        self.assertEqual(stats["valid_links"], 3)
        self.assertEqual(stats["valid_items"], 2)
        self.assertEqual(stats["rejected_items"], 2)
        self.assertEqual(stats["rejection_reasons"]["invalid_or_missing_price"], 1)
        malformed = SAMPLE.replace(b"</channel></rss>", b"</channel>")
        with patch.object(feed, "_persist_staged_offers") as persist:
            with self.assertRaisesRegex(feed.FeedImportError, "notino_feed_invalid_xml"):
                feed.import_feed_bytes(malformed)
            persist.assert_not_called()

    def test_catalog_with_nonstandard_item_tags_is_still_supported(self):
        item = SAMPLE.split(b"<item>", 1)[1].split(b"</item>", 1)[0]
        payload = (b"<catalog xmlns:g='http://base.google.com/ns/1.0'><offer>" + item
                   + b"</offer><offer>" + item.replace(b"LB100", b"OTHER")
                   + b"</offer></catalog>")
        self.assertEqual(len(feed.parse_feed(payload)), 2)

    def test_missing_size_is_valid_and_does_not_change_feed_identity(self):
        unknown_size = SAMPLE.replace(b" 100 ml", b"").replace(b"<g:size>100 ml</g:size>", b"")
        first = feed.parse_feed(unknown_size)[0]
        second = feed.parse_feed(SAMPLE)[0]
        self.assertIsNone(first.size_ml)
        self.assertEqual(feed._stable_variant_key(first), feed._stable_variant_key(second))

    def test_staging_publication_is_atomic_and_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            db = sqlite3.connect(path)
            db.executescript("""
                CREATE TABLE store_urls(store TEXT, url TEXT, slug TEXT, lastmod TEXT,
                    discovered_at REAL, active INTEGER, PRIMARY KEY(store,url));
                CREATE TABLE store_products(store TEXT, url TEXT, name TEXT, brand TEXT,
                    image TEXT, sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL,
                    concentration TEXT, gender TEXT, price REAL, currency TEXT,
                    availability TEXT, fetched_at REAL, fetch_status TEXT, PRIMARY KEY(store,url));
                CREATE TABLE store_product_variants(store TEXT, url TEXT, variant_key TEXT,
                    name TEXT, brand TEXT, image TEXT, sku TEXT, gtin TEXT, mpn TEXT,
                    size_ml REAL, concentration TEXT, gender TEXT, price REAL, currency TEXT,
                    availability TEXT, fetched_at REAL, variant_url TEXT,
                    PRIMARY KEY(store,url,variant_key));
                CREATE TABLE hydration_queue(store TEXT, url TEXT, state TEXT, priority INTEGER,
                    attempts INTEGER, available_at REAL, first_seen_at REAL, leased_until REAL,
                    lease_token TEXT, last_error TEXT, PRIMARY KEY(store,url));
                CREATE TABLE sync_state(store TEXT PRIMARY KEY, status TEXT, started_at REAL,
                    finished_at REAL, discovered_count INTEGER, fetched_count INTEGER, error TEXT);
            """)
            db.close()
            with patch.dict("sys.modules", {"catalog_engine": types.SimpleNamespace(DB_PATH=path)}):
                with patch.dict(os.environ, {"NOTINO_PERSIST_PROFILE": "1"}):
                    with self.assertLogs("scenthunter.notino_feed", level="INFO") as profile:
                        result = feed.import_feed_bytes(SAMPLE)
                self.assertIn("'commit':", " ".join(profile.output))
                self.assertEqual(result["imported_offers"], 2)
                self.assertEqual(result["rejected_items"], 2)
                db = sqlite3.connect(path)
                db.execute("UPDATE store_product_variants SET variant_key=? WHERE size_ml=100",
                           ("100ml:6291108730001",))
                db.commit()
                db.close()
                feed.import_feed_bytes(SAMPLE)
                db = sqlite3.connect(path)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM store_product_variants").fetchone()[0], 2)
                before = db.execute("SELECT * FROM sync_state").fetchall()
                db.close()
                partial = SAMPLE.replace(b"69.90 EUR", b"0 EUR")
                with self.assertRaisesRegex(feed.FeedImportError, "notino_feed_suspicious_offer_count"):
                    feed.import_feed_bytes(partial)
                with self.assertRaisesRegex(feed.FeedImportError, "notino_feed_invalid_xml"):
                    feed.import_feed_bytes(SAMPLE.replace(b"</channel></rss>", b"</channel>"))
                db = sqlite3.connect(path)
                self.assertEqual(db.execute("SELECT * FROM sync_state").fetchall(), before)
                db.execute("""CREATE TRIGGER reject_second_variant BEFORE UPDATE ON store_product_variants
                    WHEN NEW.name LIKE '%Limited Edition%'
                    BEGIN SELECT RAISE(ABORT, 'injected failure'); END""")
                db.commit()
                db.close()
                with self.assertRaises(sqlite3.IntegrityError):
                    feed.import_feed_bytes(SAMPLE.replace(b"49,90 EUR", b"59,90 EUR"))
                db = sqlite3.connect(path)
                self.assertEqual(db.execute("SELECT * FROM sync_state").fetchall(), before)
                self.assertEqual(db.execute("SELECT price FROM store_product_variants WHERE size_ml=100").fetchone()[0], 49.9)
                db.close()

    def test_incomplete_archives_and_unsafe_xml_fail_closed(self):
        broken_gzip = gzip.compress(SAMPLE)[:-8]
        unsafe = SAMPLE.replace(b"<rss", b'<!DOCTYPE rss [<!ENTITY x "x">]><rss', 1)
        for payload in (broken_gzip, unsafe):
            with self.subTest(payload=payload[:20]), patch.object(feed, "_persist_staged_offers") as persist:
                with self.assertRaises(feed.FeedImportError):
                    feed.import_feed_bytes(payload)
                persist.assert_not_called()

    def test_expired_import_never_publishes(self):
        with patch.object(feed, "_persist_staged_offers") as persist:
            with self.assertRaisesRegex(feed.FeedImportError, "notino_feed_import_timeout"):
                feed._import_stream(io.BytesIO(SAMPLE), 0, deadline=0)
            persist.assert_not_called()

    def test_imported_offer_is_searchable_in_catalog(self):
        import catalog_engine

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            with patch.object(catalog_engine, "DB_PATH", path), patch.object(catalog_engine, "_SCHEMA_READY", False):
                conn = catalog_engine.db()
                conn.close()
                feed.import_feed_bytes(SAMPLE)
                rows = catalog_engine._search_local_impl("French Avenue Liquid Brun", per_store=32)
                self.assertTrue(any(row.get("store_key") == "notino" and row.get("price_num") == 49.9
                                    for row in rows))

    def test_invalid_feeds_fail_closed(self):
        cases = [
            (b"", "notino_feed_empty"),
            (b"<rss><item>", "notino_feed_invalid_xml"),
            (b"<html><body>Access denied</body></html>", "notino_feed_unrecognized_root"),
            (b"<!DOCTYPE rss [<!ENTITY x SYSTEM 'file:///etc/passwd'>]><rss/>",
             "notino_feed_unsafe_xml_declaration"),
            (b"<rss><channel><item><title>No price 100 ml</title></item></channel></rss>",
             "notino_feed_no_valid_priced_fr_offers"),
        ]
        for payload, error in cases:
            with self.subTest(error=error):
                with self.assertRaisesRegex(feed.FeedImportError, error):
                    feed.parse_feed(payload)

    def test_product_url_requires_https_and_notino_fr(self):
        self.assertIsNone(feed._product_url("https://www.notino.de/brand/item/"))
        self.assertIsNone(feed._product_url("http://www.notino.fr/brand/item/"))
        self.assertIsNone(feed._product_url("https://user:pass@www.notino.fr/brand/item/"))

    def test_brand_slugs_are_not_rejected_as_reserved_route_prefixes(self):
        self.assertEqual(
            feed._product_url("https://www.notino.fr/parfums-de-marly/percival/"),
            "https://www.notino.fr/parfums-de-marly/percival/",
        )
        self.assertEqual(
            feed._product_url("https://www.notino.fr/carthusia/mediterraneo/"),
            "https://www.notino.fr/carthusia/mediterraneo/",
        )
        self.assertIsNone(feed._product_url("https://www.notino.fr/parfums/"))
        self.assertIsNone(feed._product_url("https://www.notino.fr/cart/"))

    def test_cj_click_url_resolves_notino_product_and_preserves_affiliate_link(self):
        click_url = (
            "https://www.anrdoezrs.net/click-101918103-13485502"
            "?url=https%3A%2F%2Fwww.notino.fr%2Frasasi%2Fhawas-eau-de-parfum%2F"
        )
        xml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>
          <item><g:id>HAWAS100</g:id><g:title>Rasasi Hawas Eau de Parfum 100 ml</g:title>
          <g:brand>Rasasi</g:brand><g:price>42.90 EUR</g:price>
          <g:availability>in stock</g:availability><g:link>{click_url}</g:link>
          <g:size>100 ml</g:size></item>
        </channel></rss>""".encode("utf-8")

        offers = feed.parse_feed(xml)

        self.assertEqual(len(offers), 1)
        self.assertEqual(
            offers[0].url,
            "https://www.notino.fr/rasasi/hawas-eau-de-parfum/",
        )
        self.assertEqual(offers[0].affiliate_url, click_url)
        self.assertEqual(
            feed._product_url(click_url),
            "https://www.notino.fr/rasasi/hawas-eau-de-parfum/",
        )

    def test_cj_click_url_rejects_untrusted_hosts_and_targets(self):
        self.assertIsNone(feed._product_url(
            "https://evil.example/click-101918103-13485502"
            "?url=https%3A%2F%2Fwww.notino.fr%2Frasasi%2Fhawas%2F"
        ))
        self.assertIsNone(feed._product_url(
            "https://www.anrdoezrs.net/click-101918103-13485502"
            "?url=https%3A%2F%2Fwww.notino.de%2Frasasi%2Fhawas%2F"
        ))

    def test_search_validates_cj_urls_without_changing_other_retailers(self):
        import catalog_engine

        product = "https://www.notino.fr/dior/sauvage-eau-de-parfum/"
        click = "https://www.anrdoezrs.net/click-101918103-13485502?url="

        def link(destination):
            return click + quote(destination, safe="")

        valid = link(product)
        tracking = link(product + "?utm_source=cj&utm_campaign=parfum%20homme")
        cases = [
            (valid, valid),
            (tracking, tracking),
            (link(product.replace("sauvage", "miss-dior")), product),
            (valid.replace("www.anrdoezrs.net", "anrdoezrs.net.evil.example"), product),
            (valid.replace("https://www.anrdoezrs.net", "http://www.anrdoezrs.net"), product),
            (valid + "&url=", product),
            (valid + "&%75rl=" + quote(product, safe=""), product),
            (valid + "&%2575rl=" + quote(product, safe=""), product),
            (valid + ";url=" + quote(product, safe=""), product),
            (valid + "&sid=unobserved", product),
            (link(product.replace("notino.fr", "notino.de")), product),
            (valid.replace("click-101918103-13485502", "redirect"), product),
            (valid + "#fragment", product),
            (link(product + "?redirect=https%3A%2F%2Fevil.example"), product),
            (link(product + "../other/"), product),
            (link(product.replace("/dior/", "/dior%2Fother/")), product),
            (link(product.replace("/dior/", "/dior%252Fother/")), product),
            (link(product.replace("/dior/", "/dior%5Cother/")), product),
            (valid + "&sid=%ZZ", product),
            ("https://[invalid", product),
            (product + "?variant=100", product + "?variant=100"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(catalog_engine._notino_variant_url(raw, product), expected)
        encoded_product = "https://www.notino.fr/dior/parfum-%C3%A9dition/"
        self.assertEqual(feed.validated_cj_offer_url(link(encoded_product), encoded_product), link(encoded_product))
        for unsafe_path in (
            "/dior/%2e%2e/other/",
            "/dior%2Fother/",
            "/dior%252Fother/",
            "/dior%5Cother/",
            "/dior;parameter/other/",
            "/dior%3Bparameter/other/",
        ):
            unsafe_product = "https://www.notino.fr" + unsafe_path
            with self.subTest(unsafe_path=unsafe_path):
                self.assertIsNone(feed.validated_cj_offer_url(link(unsafe_product), unsafe_product))
        self.assertIsNone(catalog_engine._store_allowed_variant_url("sabina", valid, product))
        self.assertIsNone(catalog_engine._store_allowed_url("notino", valid, product))
        self.assertIsNone(catalog_engine._notino_variant_url(valid, "https://evil.example/item"))

    def test_cj_offer_survives_import_database_search_and_publication(self):
        import catalog_engine
        import main
        from fastapi.testclient import TestClient

        product = "https://www.notino.fr/dior/sauvage-eau-de-parfum/"
        click = (
            "https://www.anrdoezrs.net/click-101918103-13485502?url="
            + quote(product, safe="")
        )
        xml = f"""<rss xmlns:g="http://base.google.com/ns/1.0"><channel>
          <item><g:id>SAUVAGE100</g:id><g:title>Dior Sauvage Eau de Parfum 100 ml</g:title>
          <g:brand>Dior</g:brand><g:price>89.90 EUR</g:price>
          <g:availability>in stock</g:availability><g:link>{html.escape(click)}</g:link>
          <g:size>100 ml</g:size></item></channel></rss>""".encode()

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "catalog.sqlite"
            with patch.object(catalog_engine, "DB_PATH", path), \
                 patch.object(catalog_engine, "_SCHEMA_READY", False), \
                 patch.object(catalog_engine, "ACTIVE_STORES", ("notino",)), \
                 patch.object(catalog_engine, "_schedule_easycosmetic_missing_size_repairs"), \
                 patch.object(catalog_engine, "_schedule_stale_price_repairs"), \
                 patch.object(main, "_catalog_search_terms", return_value=["Dior Sauvage"]), \
                 patch.object(main, "catalog_refresh_candidates", None), \
                 patch.object(main, "STORES", ["notino"]):
                catalog_engine.db().close()
                self.assertEqual(feed.import_feed_bytes(xml)["imported_offers"], 1)
                conn = catalog_engine.db()
                row = conn.execute(
                    "SELECT url, variant_url FROM store_product_variants WHERE store='notino'"
                ).fetchone()
                self.assertEqual((row["url"], row["variant_url"]), (product, click))
                conn.close()

                rows = catalog_engine.search_local("Dior Sauvage")
                self.assertEqual([(r["product_url"], r["url"]) for r in rows], [(product, click)])
                feed_rows = feed.search_feed("Dior Sauvage")["results"]
                self.assertEqual([(r["product_url"], r["url"]) for r in feed_rows], [(product, click)])

                response = TestClient(main.app).get("/search", params={"q": "Dior Sauvage"})
                self.assertEqual(response.status_code, 200)
                result = response.json()
                public_offers = [
                    offer for group in result["results"] for offer in group["offers"]
                ] + result["unresolved_offers"]
                self.assertEqual([offer["url"] for offer in public_offers], [click])
                self.assertEqual([offer["product_url"] for offer in public_offers], [product])

                conn = catalog_engine.db()
                conn.execute(
                    "UPDATE store_product_variants SET variant_url=? WHERE store='notino'",
                    (click + "&url=",),
                )
                conn.commit()
                conn.close()
                self.assertEqual(catalog_engine.search_local("Dior Sauvage")[0]["url"], product)
                self.assertEqual(feed.search_feed("Dior Sauvage")["results"][0]["url"], product)
                result = TestClient(main.app).get("/search", params={"q": "Dior Sauvage"}).json()
                public_offers = [
                    offer for group in result["results"] for offer in group["offers"]
                ] + result["unresolved_offers"]
                self.assertEqual([offer["url"] for offer in public_offers], [product])
                conn = catalog_engine.db()
                conn.execute("DROP TABLE catalog_search_fts")
                conn.commit()
                conn.close()
                self.assertEqual(catalog_engine.search_local("Dior Sauvage")[0]["url"], product)
                conn = catalog_engine.db()
                conn.execute(
                    "UPDATE store_product_variants SET variant_url=? WHERE store='notino'", (click,)
                )
                conn.commit()
                conn.close()
                legacy_rows = catalog_engine.search_local("Dior Sauvage")
                self.assertEqual([(r["product_url"], r["url"]) for r in legacy_rows], [(product, click)])

    def test_missing_credentials_are_reported_without_secrets(self):
        values = {
            "NOTINO_CJ_FEED_URL": "",
            "NOTINO_CJ_FEED_USERNAME": "",
            "NOTINO_CJ_FEED_PASSWORD": "",
            "CJ_HTTP_USERNAME": "",
            "CJ_HTTP_PASSWORD": "secret-canary-value",
        }
        with patch.dict(os.environ, values, clear=False):
            with self.assertRaisesRegex(feed.FeedImportError, "notino_feed_credentials_missing") as raised:
                feed.import_configured_feed()
        self.assertNotIn("secret-canary-value", str(raised.exception))

    def test_default_cj_subscription_url_is_configured(self):
        self.assertIn("/324587/", feed.DEFAULT_CJ_FEED_URL)
        self.assertTrue(feed.DEFAULT_CJ_FEED_URL.endswith(".xml.zip"))
