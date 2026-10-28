"""Regression coverage for incomplete Deloox hydration recovery at startup."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import backend.catalog_engine as catalog_engine


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
