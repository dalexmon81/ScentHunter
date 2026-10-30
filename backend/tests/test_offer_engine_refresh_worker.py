import sqlite3
import unittest
from types import SimpleNamespace

try:
    from offer_engine.refresh_worker import _next_query, _record_result, build_product_queries
except ModuleNotFoundError:
    from backend.offer_engine.refresh_worker import _next_query, _record_result, build_product_queries


class RefreshWorkerQueryTests(unittest.TestCase):
    def test_builds_one_brand_qualified_query_per_product_with_variants(self):
        catalog = SimpleNamespace(all_products=lambda: [
            SimpleNamespace(brand="Lattafa", name="Liquid Brun", variants=[
                SimpleNamespace(size_ml=100, label=None),
                SimpleNamespace(size_ml=150, label="Liquid Brun Limited Edition"),
            ]),
            SimpleNamespace(brand="Lattafa", name="Liquid Brun", variants=[
                SimpleNamespace(size_ml=100, label=None),
            ]),
            SimpleNamespace(brand="Rasasi", name="Hawas", variants=[]),
            SimpleNamespace(brand="Afnan", name="9PM", variants=[
                SimpleNamespace(size_ml=100, label=None),
            ]),
            SimpleNamespace(brand="Dior", name="Sauvage", variants=[
                SimpleNamespace(size_ml=60, label="Elixir"),
            ]),
        ])
        self.assertEqual(
            build_product_queries(catalog),
            [
                "Lattafa Liquid Brun 100 ml",
                "Lattafa Liquid Brun Limited Edition 150 ml",
                "Afnan 9PM 100 ml",
                "Dior Sauvage Elixir 60 ml",
            ],
        )

    def test_empty_catalog_returns_no_queries(self):
        catalog = SimpleNamespace(all_products=lambda: [])
        self.assertEqual(build_product_queries(catalog), [])

    def test_refresh_cursor_rotates_and_persists(self):
        connection = sqlite3.connect(":memory:")
        connection.execute("""
            CREATE TABLE sh_refresh_scheduler (
                id INTEGER PRIMARY KEY,
                product_cursor INTEGER NOT NULL DEFAULT 0,
                last_started_at TEXT,
                last_finished_at TEXT,
                last_error TEXT
            )
        """)
        self.assertEqual(_next_query(connection, ["Lattafa Liquid Brun", "Rasasi Hawas"]), "Lattafa Liquid Brun")
        self.assertEqual(_next_query(connection, ["Lattafa Liquid Brun", "Rasasi Hawas"]), "Rasasi Hawas")
        self.assertEqual(_next_query(connection, ["Lattafa Liquid Brun", "Rasasi Hawas"]), "Lattafa Liquid Brun")
        _record_result(connection, "test_error")
        row = connection.execute(
            "SELECT last_finished_at, last_error FROM sh_refresh_scheduler WHERE id=1"
        ).fetchone()
        self.assertIsNotNone(row[0])
        self.assertEqual(row[1], "test_error")
        connection.close()

    def test_fly_bootstrap_migration_precedes_refresh_worker_and_is_opt_in(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[2]
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        fly_config = (root / "fly.toml").read_text(encoding="utf-8")
        migration = dockerfile.index("apply_migration; apply_migration()")
        worker = dockerfile.index("python -m offer_engine.refresh_worker")
        self.assertLess(migration, worker)
        self.assertIn('SCENTHUNTER_OFFER_ENGINE_BOOTSTRAP_MIGRATION = "0"', fly_config)
        self.assertIn('SCENTHUNTER_OFFER_ENGINE_REFRESH_WORKER_ENABLED = "0"', fly_config)
        self.assertIn('SCENTHUNTER_OFFER_ENGINE_API_ENABLED = "0"', fly_config)
        self.assertIn('SCENTHUNTER_OFFER_ENGINE_SEARCH_ENABLED = "0"', fly_config)


if __name__ == "__main__":
    unittest.main()
