"""Cumulative Al Wataniah catalog coverage guard for the current official audit."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

IDENTITY_ONLY = {"House Of Oud", "Anwan"}


class AlWataniahCumulativeCoverageTests(unittest.TestCase):
    def test_current_cumulative_identity_and_variant_totals(self):
        products = [
            p for p in CATALOG["products"]
            if p.get("brand") == "Al Wataniah"
        ]
        self.assertEqual(len(products), 86)
        self.assertTrue(all(p.get("identity_status") == "source_verified_name" for p in products))

        product_by_id = {p["product_id"]: p for p in products}
        variants = [
            v for v in CATALOG["variants"]
            if v.get("product_id") in product_by_id
        ]
        self.assertEqual(len(variants), 84)
        self.assertEqual(len({v["product_id"] for v in variants}), 84)

        variants_by_product = {}
        for variant in variants:
            variants_by_product.setdefault(variant["product_id"], []).append(variant)

        without_variants = {
            p["canonical_name"] for p in products
            if p["product_id"] not in variants_by_product
        }
        self.assertEqual(without_variants, IDENTITY_ONLY)

    def test_all_84_variants_are_official_100ml_edp_and_registry_aligned(self):
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "al_wataniah_catalog"
        )
        family_products = {
            p["canonical_name"]: p for p in family["products"]
        }
        products = [
            p for p in CATALOG["products"]
            if p.get("brand") == "Al Wataniah"
        ]
        product_by_id = {p["product_id"]: p for p in products}
        variants = [
            v for v in CATALOG["variants"]
            if v.get("product_id") in product_by_id
        ]

        for variant in variants:
            with self.subTest(variant=variant.get("variant_id")):
                product = product_by_id[variant["product_id"]]
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(
                    variant.get("source_evidence_url"),
                    product.get("source_product_url"),
                )
                self.assertTrue(
                    (variant.get("source_evidence_url") or "").startswith(
                        "https://www.alwataniah.com/products/"
                    )
                )
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(family_products[product["canonical_name"]].get("formats_ml"), [100])

    def test_two_identity_only_products_have_official_identity_evidence_but_no_variant(self):
        products = {
            p["canonical_name"]: p for p in CATALOG["products"]
            if p.get("brand") == "Al Wataniah"
        }
        family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "al_wataniah_catalog"
        )
        family_products = {
            p["canonical_name"]: p for p in family["products"]
        }
        for name in IDENTITY_ONLY:
            with self.subTest(product=name):
                product = products[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertTrue(
                    (product.get("source_product_url") or "").startswith(
                        "https://www.alwataniah.com/products/"
                    )
                )
                self.assertNotIn("formats_ml", product)
                self.assertNotIn("concentration", product)
                self.assertFalse(
                    any(v.get("product_id") == product["product_id"] for v in CATALOG["variants"])
                )
                self.assertNotIn("formats_ml", family_products[name])

    def test_no_commercial_offer_fields_in_al_wataniah_variants(self):
        forbidden = {
            "price", "price_amount", "currency", "availability", "stock",
            "in_stock", "offer_url", "retailer", "store_id", "shipping_cost",
        }
        product_ids = {
            p["product_id"] for p in CATALOG["products"]
            if p.get("brand") == "Al Wataniah"
        }
        for variant in CATALOG["variants"]:
            if variant.get("product_id") in product_ids:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()
