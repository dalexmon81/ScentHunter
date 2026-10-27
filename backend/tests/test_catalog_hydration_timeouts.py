"""Regression tests for retailer-specific catalog hydration timeouts."""
import unittest

import catalog_engine


class CatalogHydrationTimeoutTests(unittest.TestCase):
    def test_deloox_has_bounded_but_less_aggressive_read_timeout(self):
        self.assertEqual(
            catalog_engine._refresh_timeout_for_store("deloox"),
            (3.0, 8.0),
        )

    def test_easycosmetic_keeps_its_existing_long_timeout(self):
        self.assertEqual(
            catalog_engine._refresh_timeout_for_store("easycosmetic"),
            max(25, catalog_engine.REFRESH_TIMEOUT),
        )

    def test_other_stores_keep_the_default_refresh_timeout(self):
        self.assertEqual(
            catalog_engine._refresh_timeout_for_store("parfumzentrum"),
            catalog_engine.REFRESH_TIMEOUT,
        )


if __name__ == "__main__":
    unittest.main()
