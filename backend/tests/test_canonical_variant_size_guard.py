"""Regression coverage for canonical sellable-variant size validation."""

import unittest

from product_matcher import ProductMatcher


class CanonicalVariantSizeGuardTests(unittest.TestCase):
    def _matcher(self):
        return ProductMatcher([
            {
                "product_id": "SH-0031",
                "brand": "French Avenue",
                "name": "Liquid Brun Limited Edition",
                "family_name": "Liquid Brun Limited Edition",
                "formats_ml": [150],
            }
        ])

    def test_family_variant_rejects_retailer_size_not_in_canonical_formats(self):
        matcher = self._matcher()
        result = matcher._build_family_result(
            {
                "brand": "French Avenue",
                "name": "Liquid Brun Limited Edition",
                "size_ml": 100,
            },
            {
                "family_id": "french-avenue-liquid-brun",
                "brand": "French Avenue",
                "query_aliases": ["Liquid Brun Limited Edition"],
            },
            {
                "canonical_name": "Liquid Brun Limited Edition",
                "formats_ml": [150],
            },
        )

        self.assertEqual(result, {
            "status": "rejected",
            "reject_reason": "canonical_variant_size_mismatch",
        })

    def test_family_variant_keeps_the_verified_150_ml_format(self):
        matcher = self._matcher()
        result = matcher._build_family_result(
            {
                "brand": "French Avenue",
                "name": "Liquid Brun Limited Edition",
                "size_ml": 150,
            },
            {
                "family_id": "french-avenue-liquid-brun",
                "brand": "French Avenue",
                "query_aliases": ["Liquid Brun Limited Edition"],
            },
            {
                "canonical_name": "Liquid Brun Limited Edition",
                "formats_ml": [150],
            },
        )

        self.assertEqual(result["size_ml"], 150)
        self.assertEqual(result["variant_id"], "SH-0031:150")


if __name__ == "__main__":
    unittest.main()
