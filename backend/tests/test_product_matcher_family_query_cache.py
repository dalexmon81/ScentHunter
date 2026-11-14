"""Regression tests for per-query canonical family lookup caching."""
import unittest

from product_matcher import ProductMatcher


class ProductMatcherFamilyQueryCacheTests(unittest.TestCase):
    def test_reuses_resolved_family_for_repeated_offer_matches(self):
        matcher = ProductMatcher(
            catalog=[],
            family_registry=[{
                "family_id": "rasasi-hawas",
                "brand": "Rasasi",
                "query_aliases": ["Hawas"],
                "variants": [{"canonical_name": "Rasasi Hawas"}],
            }],
        )

        first = matcher._family_for_query("Hawas")
        second = matcher._family_for_query("  HAWAS  ")

        self.assertIsNotNone(first)
        self.assertIs(first, second)
        self.assertEqual(len(matcher._family_query_cache), 1)

    def test_caches_family_lookup_misses(self):
        matcher = ProductMatcher(catalog=[], family_registry=[])

        self.assertIsNone(matcher._family_for_query("Unknown fragrance"))
        self.assertIsNone(matcher._family_for_query(" unknown   fragrance "))
        self.assertIn("unknown fragrance", matcher._family_query_cache)
        self.assertIsNone(matcher._family_query_cache["unknown fragrance"])


if __name__ == "__main__":
    unittest.main()
