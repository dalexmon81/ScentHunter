"""Contract test for the Notino feed staging indexes used during publication."""
import sqlite3
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from scrapers.notino import affiliate_feed as feed


SAMPLE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>
 <item><g:id>LB100</g:id><g:title>French Avenue Liquid Brun Eau de Parfum 100 ml</g:title>
 <g:brand>French Avenue</g:brand><g:gtin>6291108730001</g:gtin><g:price>49,90 EUR</g:price>
 <g:availability>in stock</g:availability><g:link>https://www.notino.fr/french-avenue/liquid-brun/</g:link>
 <g:size>100 ml</g:size></item>
</channel></rss>"""


class NotinoFeedStagingIndexTests(unittest.TestCase):
    def test_import_builds_url_grouping_index_before_publication(self):
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
            db.commit()
            db.close()

            observed = {}
            def inspect_stage(stage, count, started_at, deadline):
                names = {row[1] for row in stage.execute("PRAGMA index_list(offers)")}
                observed["legacy"] = "idx_notino_offers_legacy_url" in names
                observed["url_slug"] = "idx_notino_offers_url_slug" in names

            with patch.dict("sys.modules", {"catalog_engine": types.SimpleNamespace(DB_PATH=path)}), \
                 patch.object(feed, "_persist_staged_offers", side_effect=inspect_stage):
                feed.import_feed_bytes(SAMPLE)

            self.assertTrue(observed["legacy"])
            self.assertTrue(observed["url_slug"])


if __name__ == "__main__":
    unittest.main()
