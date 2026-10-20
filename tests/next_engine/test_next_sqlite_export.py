import json
import tempfile
import unittest
from pathlib import Path
from scenthunter_next_engine.repository import SQLiteOfferRepository
from scenthunter_next_engine.next_sqlite_export import export_next_catalog
from test_repository import observation

class NextSQLiteExportTests(unittest.TestCase):
    def test_export_current_offers_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); db = root / 'next.sqlite3'; out = root / 'snapshot.json'
            repo = SQLiteOfferRepository(db)
            repo.save_observation(observation())
            data = export_next_catalog(db, out, limit=10)
            self.assertTrue(data['read_only'])
            self.assertEqual(len(data['rows']), 1)
            self.assertEqual(data['rows'][0]['price'], 129.99)
            self.assertEqual(json.loads(out.read_text())['source'], 'scenthunter_next_sqlite')
    def test_export_refuses_legacy_database_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); db = root / 'legacy.sqlite3'; out = root / 'snapshot.json'
            import sqlite3
            conn = sqlite3.connect(db); conn.execute('CREATE TABLE store_products (store TEXT)'); conn.commit(); conn.close()
            with self.assertRaisesRegex(ValueError, 'not a next-engine database'):
                export_next_catalog(db, out)
    def test_export_refuses_same_output_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / 'next.sqlite3'; SQLiteOfferRepository(db)
            with self.assertRaisesRegex(ValueError, 'output path'):
                export_next_catalog(db, db)

if __name__ == '__main__': unittest.main()
