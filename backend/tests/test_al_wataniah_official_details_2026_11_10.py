"""Official Al Wataniah product-page evidence for three catalog identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Rawaee Noble": "https://www.alwataniah.com/products/rawaee-noble",
    "Rawaee Regina": "https://www.alwataniah.com/products/rawaee-regina",
    "Redaa": "https://www.alwataniah.com/products/redaa",
}


class AlWataniahOfficialDetailsTests(unittest.TestCase):
    def test_three_official_product_pages_confirm_identity_size_and_concentration(self):
        variants = CATALOG["variants"]
        families = {family["family_id"]: family for family in REGISTRY["families"]}
        for name, source in EXPECTED.items():
            with self.subTest(product=name):
                products = [
                    row for row in CATALOG["products"]
                    if row.get("brand_name", row.get("brand")) == "Al Wataniah"
                    and row.get("canonical_name") == name
                ]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertEqual(product.get("source_product_url"), source)
                self.assertEqual(product.get("source_evidence_url"), source)
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                matches = [
                    row for row in variants
                    if row.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(matches), 1)
                variant = matches[0]
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("source_url"), source)
                self.assertEqual(variant.get("source_evidence_url"), source)
                family = families[product["family_id"]]
                family_rows = [
                    row for row in family["products"]
                    if row.get("canonical_name") == name
                ]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0].get("formats_ml"), [100])

    def test_product_variant_and_gtin_identity_integrity(self):
        products = CATALOG["products"]
        variants = CATALOG["variants"]
        product_ids = [row.get("product_id") for row in products]
        variant_ids = [row.get("variant_id") for row in variants]
        gtins = [row.get("gtin") for row in variants if row.get("gtin")]
        known_ids = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertTrue(all(row.get("product_id") in known_ids for row in variants))

    def test_no_retail_offer_fields_were_added(self):
        forbidden = {"price", "currency", "availability", "stock", "offer_url", "retailer", "shipping_cost"}
        products = {row["product_id"]: row for row in CATALOG["products"]}
        for variant in CATALOG["variants"]:
            if products[variant["product_id"]]["canonical_name"] in EXPECTED:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()
