import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scenthunter_next_engine.sqlite_export import export_catalog


class SQLiteExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.db = self.root / "catalog.sqlite3"
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE store_products (
                store TEXT NOT NULL, url TEXT NOT NULL, name TEXT, brand TEXT,
                price REAL, currency TEXT, size_ml REAL, fetched_at REAL,
                fetch_status TEXT, PRIMARY KEY(store,url));
            CREATE TABLE store_product_variants (
                store TEXT NOT NULL, url TEXT NOT NULL, variant_key TEXT NOT NULL,
                name TEXT, brand TEXT, size_ml REAL, price REAL, currency TEXT,
                availability TEXT, fetched_at REAL, variant_url TEXT,
                PRIMARY KEY(store,url,variant_key));
            CREATE TABLE store_urls (
                store TEXT NOT NULL, url TEXT NOT NULL, slug TEXT, lastmod TEXT,
                discovered_at REAL, active INTEGER, PRIMARY KEY(store,url));
            INSERT INTO store_products VALUES ('deloox','https://example.test/a','Perfume A','Brand A',49.9,'EUR',100,1,'ok');
            INSERT INTO store_products VALUES ('sabina','https://example.test/b','Perfume B','Brand B',39.9,'EUR',50,1,'ok');
            INSERT INTO store_product_variants VALUES ('deloox','https://example.test/a','100ml','Perfume A','Brand A',100,49.9,'EUR','in_stock',1,'https://example.test/a?size=100');
            INSERT INTO store_urls VALUES ('deloox','https://example.test/a','perfume-a',NULL,1,1);
        """)
        conn.commit()
        conn.close()

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_only_export_filters_store_and_keeps_variants(self):
        out = self.root / "snapshot.json"
        result = export_catalog(self.db, out, store="DELOOX")
        self.assertTrue(result["read_only"])
        data = json.loads(out.read_text())
        products = data["tables"]["store_products"]["rows"]
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["name"], "Perfume A")
        self.assertEqual(len(data["tables"]["store_product_variants"]["rows"]), 1)
        self.assertFalse(data["tables"]["store_products"]["truncated"])
        conn = sqlite3.connect(self.db)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM store_products").fetchone()[0], 2)
        conn.close()

    def test_export_rejects_database_as_output(self):
        with self.assertRaises(ValueError):
            export_catalog(self.db, self.db)

    def test_row_limit_marks_truncation(self):
        out = self.root / "limited.json"
        data = export_catalog(self.db, out, limit_per_table=1)
        self.assertTrue(data["tables"]["store_products"]["truncated"])
        self.assertEqual(len(data["tables"]["store_products"]["rows"]), 1)

    def test_missing_table_is_reported_not_created(self):
        conn = sqlite3.connect(self.db)
        conn.execute("DROP TABLE store_urls")
        conn.commit()
        conn.close()
        out = self.root / "missing.json"
        data = export_catalog(self.db, out)
        self.assertFalse(data["tables"]["store_urls"]["present"])
        conn = sqlite3.connect(self.db)
        self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='store_urls'").fetchone())
        conn.close()


if __name__ == "__main__":
    unittest.main()
