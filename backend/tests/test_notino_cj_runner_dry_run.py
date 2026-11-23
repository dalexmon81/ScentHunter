"""Regression tests for the read-only live Notino four-GTIN release gate."""

import unittest
from types import SimpleNamespace

from scripts.notino_cj_runner_dry_run import REVIEWED_GTINS, validate_reviewed_gtins


def make_offer(gtin, expected):
    return SimpleNamespace(
        gtin=gtin,
        external_id=expected["external_product_id"],
        title=f"Dior Sauvage Eau de Parfum {expected['size_ml']} ml",
        brand="Dior",
        concentration="Eau de Parfum",
        size_ml=float(expected["size_ml"]),
        price=99.90,
        currency="EUR",
        availability="in_stock",
        url="https://www.notino.fr" + expected["path"],
    )


class NotinoLiveFourGtinGateTests(unittest.TestCase):
    def test_all_four_exact_reviewed_variants_pass(self):
        offers = [make_offer(gtin, expected) for gtin, expected in REVIEWED_GTINS.items()]
        result = validate_reviewed_gtins(offers)

        self.assertTrue(result["passed"])
        self.assertEqual(result["expected_gtins"], 4)
        self.assertEqual(result["verified_gtins"], 4)
        self.assertEqual(result["failures"], [])

    def test_missing_variant_fails_even_when_feed_has_other_offers(self):
        offers = [
            make_offer(gtin, expected)
            for index, (gtin, expected) in enumerate(REVIEWED_GTINS.items())
            if index != 2
        ]
        result = validate_reviewed_gtins(offers)

        self.assertFalse(result["passed"])
        self.assertEqual(result["verified_gtins"], 3)
        self.assertTrue(any(item["gtin"] == "3348901368247"
                            for item in result["failures"]))

    def test_wrong_size_or_product_url_fails_identity_gate(self):
        offers = [make_offer(gtin, expected) for gtin, expected in REVIEWED_GTINS.items()]
        offers[0].size_ml = 50
        result = validate_reviewed_gtins(offers)

        self.assertFalse(result["passed"])
        failed = next(item for item in result["failures"]
                      if item["gtin"] == "3348901608053")
        self.assertIn("size_ml", failed["failed_checks"])


if __name__ == "__main__":
    unittest.main()
