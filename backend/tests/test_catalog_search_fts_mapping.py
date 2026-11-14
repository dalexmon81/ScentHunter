"""Regression tests for indexed FTS row mapping and catalog triggers."""
import sqlite3
import unittest

import catalog_engine


class CatalogSearchFTSMappingTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE store_urls(
                store TEXT NOT NULL, url TEXT NOT NULL, slug TEXT NOT NULL,
                lastmod TEXT, discovered_at REAL NOT NULL,
                active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(store,url)
            )
        """)
        self.conn.execute("""
            CREATE TABLE store_products(
                store TEXT NOT NULL, url TEXT NOT NULL, name TEXT, brand TEXT,
                image TEXT, sku TEXT, gtin TEXT, mpn TEXT, size_ml REAL,
                concentration TEXT, gender TEXT, price REAL, currency TEXT,
                availability TEXT, fetched_at REAL, fetch_status TEXT,
                PRIMARY KEY(store,url)
            )
        """)
        self.conn.execute(
            "INSERT INTO store_urls(store,url,slug,discovered_at,active) VALUES(?,?,?,?,1)",
            ("notino", "https://www.notino.fr/a/", "initial-fragrance", 1.0),
        )
        self.assertTrue(catalog_engine._ensure_search_fts(self.conn))

    def tearDown(self):
        self.conn.close()

    def _matches(self, token):
        return self.conn.execute(
            "SELECT url FROM catalog_search_fts WHERE catalog_search_fts MATCH ?",
            (token,),
        ).fetchall()

    def test_mapping_uses_indexed_store_url_lookup(self):
        plan = self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM catalog_search_fts_map "
            "WHERE store=? AND url=?",
            ("notino", "https://www.notino.fr/a/"),
        ).fetchall()
        details = " ".join(str(row[3]).upper() for row in plan)
        self.assertIn("INDEX", details)

    def test_url_and_product_triggers_keep_fts_and_mapping_consistent(self):
        self.assertEqual(len(self._matches("initial")), 1)

        self.conn.execute(
            "UPDATE store_urls SET slug=? WHERE store=? AND url=?",
            ("updated-fragrance", "notino", "https://www.notino.fr/a/"),
        )
        self.assertEqual(len(self._matches("initial")), 0)
        self.assertEqual(len(self._matches("updated")), 1)

        self.conn.execute(
            """INSERT INTO store_products(store,url,name,brand,fetch_status)
               VALUES(?,?,?,?,?)""",
            ("notino", "https://www.notino.fr/a/", "Hawas Eau Parfum", "Rasasi", "OK"),
        )
        self.assertEqual(len(self._matches("rasasi")), 1)

        self.conn.execute(
            """UPDATE store_products SET name=?,brand=?
               WHERE store=? AND url=?""",
            ("Asad Eau Parfum", "Lattafa", "notino", "https://www.notino.fr/a/"),
        )
        self.assertEqual(len(self._matches("rasasi")), 0)
        self.assertEqual(len(self._matches("lattafa")), 1)

        self.conn.execute(
            "DELETE FROM store_products WHERE store=? AND url=?",
            ("notino", "https://www.notino.fr/a/"),
        )
        self.assertEqual(len(self._matches("lattafa")), 0)
        self.assertEqual(len(self._matches("updated")), 1)

        self.conn.execute(
            "DELETE FROM store_urls WHERE store=? AND url=?",
            ("notino", "https://www.notino.fr/a/"),
        )
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM catalog_search_fts_map"
        ).fetchone()[0], 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM catalog_search_fts"
        ).fetchone()[0], 0)

    def test_inactive_url_is_not_added_to_mapping_or_fts(self):
        self.conn.execute(
            """INSERT INTO store_urls(store,url,slug,discovered_at,active)
               VALUES(?,?,?,?,0)""",
            ("notino", "https://www.notino.fr/inactive/", "inactive-fragrance", 2.0),
        )
        self.assertEqual(len(self._matches("inactive")), 0)
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM catalog_search_fts_map WHERE url LIKE '%inactive%'"
        ).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
