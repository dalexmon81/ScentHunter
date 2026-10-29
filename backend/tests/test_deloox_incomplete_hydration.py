"""Regression coverage for incomplete Deloox hydration recovery at startup."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import catalog_engine


class DelooxIncompleteHydrationStartupTests(unittest.TestCase):
    def test_requeues_incomplete_null_price_row_but_preserves_complete_sold_out_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "store_catalog.sqlite3"
            with patch.object(catalog_engine, "DB_PATH", db_path), patch.object(
                catalog_engine, "_SCHEMA_READY", False
            ):
                conn = catalog_engine.db()
                try:
                    now = 1_800_000_000.0
                    conn.execute(
                        """INSERT INTO hydration_queue(
                               store,url,state,priority,attempts,available_at,first_seen_at
                           ) VALUES(?,?,?,?,?,?,?)""",
                        ("deloox", "https://www.deloox.be/produit/1385920/example.html",
                         "DONE", 100, 4, now, now - 1000),
                    )
                    conn.execute(
                        """INSERT INTO store_products(
                               store,url,name,brand,sku,gtin,size_ml,price,availability,
                               fetched_at,fetch_status
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        ("deloox", "https://www.deloox.be/produit/1385920/example.html",
                         "French Avenue Liquid Brun Extrait de Parfum Limited edition 150 ml",
                         "", "1385920", "", 150, None, "out_of_stock", now - 60, "OK"),
                    )
                    conn.execute(
                        """INSERT INTO hydration_queue(
                               store,url,state,priority,attempts,available_at,first_seen_at
                           ) VALUES(?,?,?,?,?,?,?)""",
                        ("deloox", "https://www.deloox.be/produit/99999/complete.html",
                         "DONE", 100, 1, now, now - 1000),
                    )
                    conn.execute(
                        """INSERT INTO store_products(
                               store,url,name,brand,sku,gtin,size_ml,price,availability,
                               fetched_at,fetch_status
                           ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        ("deloox", "https://www.deloox.be/produit/99999/complete.html",
                         "Example Fragrance 150 ml", "Example Brand", "99999", "",
                         150, None, "out_of_stock", now - 60, "OK"),
                    )
                    conn.commit()

                    # Simulate the next process startup/schema pass against the
                    # existing persistent database after an old parser wrote bad data.
                    catalog_engine._SCHEMA_READY = False
                    catalog_engine._ensure_schema(conn)

                    incomplete = conn.execute(
                        "SELECT state,priority,attempts FROM hydration_queue WHERE url LIKE '%/1385920/%'"
                    ).fetchone()
                    complete = conn.execute(
                        "SELECT state,priority,attempts FROM hydration_queue WHERE url LIKE '%/99999/%'"
                    ).fetchone()
                    self.assertEqual(tuple(incomplete), ("PENDING", 0, 0))
                    self.assertEqual(complete["state"], "DONE")
                    self.assertEqual(complete["attempts"], 1)
                finally:
                    conn.close()


if __name__ == "__main__":
    unittest.main()



class DelooxBrowserFallbackPageRecognitionTests(unittest.TestCase):
    def test_accepts_compact_rendered_product_document(self):
        html = (
            b'<html><head><script type="application/ld+json">'
            b'{"@type":"Product","name":"French Avenue Liquid Brun Limited Edition 150 ml",'
            b'"offers":{"price":"42.59","priceCurrency":"EUR"}}'
            b'</script></head><body><h1>French Avenue Liquid Brun Limited Edition 150 ml</h1>'
            + (b" " * 1900)
            + b"</body></html>"
        )
        self.assertTrue(catalog_engine._deloox_browser_html_is_product_candidate(html))

    def test_rejects_small_interstitial_without_product_markup(self):
        html = b"<html><body><h1>Checking your browser</h1></body></html>"
        self.assertFalse(catalog_engine._deloox_browser_html_is_product_candidate(html))

    def test_rejects_large_document_without_product_markup(self):
        html = b"<html><body>" + (b"please wait " * 250) + b"</body></html>"
        self.assertFalse(catalog_engine._deloox_browser_html_is_product_candidate(html))
