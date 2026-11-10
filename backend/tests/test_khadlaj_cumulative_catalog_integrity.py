"""Cumulative catalog integrity checks for the Khadlaj official audit chain."""
import json
import unittest
import unicodedata
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


def normalize(value):
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


class KhadlajCumulativeCatalogIntegrityTests(unittest.TestCase):
    def test_product_and_variant_ids_are_unique(self):
        products = CATALOG["products"]
        variants = CATALOG["variants"]
        product_ids = [p["product_id"] for p in products]
        variant_ids = [v["variant_id"] for v in variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

    def test_every_variant_has_an_existing_product_and_positive_size(self):
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        for variant in CATALOG["variants"]:
            with self.subTest(variant=variant.get("variant_id")):
                self.assertIn(variant["product_id"], product_ids)
                self.assertIsInstance(variant["size_ml"], (int, float))
                self.assertNotIsInstance(variant["size_ml"], bool)
                self.assertGreater(variant["size_ml"], 0)

    def test_variant_gtins_are_unique_when_present(self):
        gtins = [v["gtin"] for v in CATALOG["variants"] if v.get("gtin")]
        self.assertEqual(len(gtins), len(set(gtins)))

    def test_khadlaj_product_formats_match_variant_sizes(self):
        products_by_id = {p["product_id"]: p for p in CATALOG["products"]}
        for variant in CATALOG["variants"]:
            product = products_by_id[variant["product_id"]]
            if product.get("brand") != "Khadlaj":
                continue
            with self.subTest(product=product["canonical_name"], size=variant["size_ml"]):
                self.assertIn(variant["size_ml"], product.get("formats_ml", []))

    def test_khadlaj_family_rows_do_not_duplicate_canonical_names(self):
        for family in REGISTRY["families"]:
            if family.get("brand") != "Khadlaj":
                continue
            keys = [normalize(p.get("canonical_name")) for p in family.get("products", [])]
            self.assertEqual(len(keys), len(set(keys)), family.get("family_id"))

    def test_variant_rows_do_not_contain_retailer_offer_data(self):
        forbidden = {"price", "stock", "availability", "shipping_cost", "store_url"}
        for variant in CATALOG["variants"]:
            with self.subTest(variant=variant.get("variant_id")):
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()
