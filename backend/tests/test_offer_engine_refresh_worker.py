import unittest
from types import SimpleNamespace

from offer_engine.refresh_worker import build_product_queries


class RefreshWorkerQueryTests(unittest.TestCase):
    def test_builds_one_brand_qualified_query_per_product_with_variants(self):
        catalog = SimpleNamespace(all_products=lambda: [
            SimpleNamespace(brand="Lattafa", name="Liquid Brun", variants=[object(), object()]),
            SimpleNamespace(brand="Lattafa", name="Liquid Brun", variants=[object()]),
            SimpleNamespace(brand="Rasasi", name="Hawas", variants=[]),
            SimpleNamespace(brand="Afnan", name="9PM", variants=[object()]),
        ])
        self.assertEqual(
            build_product_queries(catalog),
            ["Lattafa Liquid Brun", "Afnan 9PM"],
        )

    def test_empty_catalog_returns_no_queries(self):
        catalog = SimpleNamespace(all_products=lambda: [])
        self.assertEqual(build_product_queries(catalog), [])


if __name__ == "__main__":
    unittest.main()
