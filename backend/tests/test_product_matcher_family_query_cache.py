"""Regression tests for cached sibling-family candidate selection."""
import unittest

from product_matcher import ProductMatcher


class ProductMatcherSiblingFamilyCacheTests(unittest.TestCase):
    def test_reuses_sibling_family_candidates_for_broad_query(self):
        matcher = ProductMatcher(
            catalog=[],
            family_registry=[
                {
                    "family_id": "liquid-brun",
                    "brand": "French Avenue",
                    "query_aliases": ["Liquid Brun"],
                    "variants": [{"canonical_name": "Liquid Brun"}],
                },
                {
                    "family_id": "liquid-brun-limited",
                    "brand": "French Avenue",
                    "query_aliases": ["Liquid Brun Limited Edition"],
                    "variants": [{"canonical_name": "Liquid Brun Limited Edition"}],
                },
            ],
        )
        family = matcher._family_for_query("Liquid Brun")
        first = matcher._sibling_family_candidates(family, "Liquid Brun")
        second = matcher._sibling_family_candidates(family, " Liquid Brun ")

        self.assertEqual([item["family_id"] for item in first], ["liquid-brun-limited"])
        self.assertIs(first, second)
        self.assertEqual(len(matcher._family_sibling_cache), 1)


if __name__ == "__main__":
    unittest.main()
