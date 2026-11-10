"""Maison Alhambra Luxe Bold and Mindset official detail evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Luxe Bold": {
        "product_id": "SH-MAISON-ALHAMBRA-30bdde3a",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-30bdde3a-100-000",
        "gtin": "6290362341130",
        "url": "https://maisonalhambra-usa.com/products/maison-alhambra-luxe-bold-eau-de-parfum-for-everyone",
    },
    "Mindset": {
        "product_id": "SH-MAISON-ALHAMBRA-64589195",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-64589195-100-000",
        "gtin": "6290362340867",
        "url": "https://maisonalhambra-usa.com/products/maison-alhambra-mindset-eau-de-parfum-for-everyone",
    },
}


class MaisonAlhambraLuxeBoldMindsetOfficialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_existing_canonical_products_are_completed_in_place(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    p for p in self.products
                    if p.get("brand_name", p.get("brand")) == "Maison Alhambra"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("product_id"), expected["product_id"])
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), expected["url"])
                self.assertEqual(product.get("source_product_url"), expected["url"])
                self.assertEqual(product.get("source_evidence_url"), expected["url"])
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("gender"), "Unisex")
                self.assertEqual(product.get("gtins"), [expected["gtin"]])

    def test_official_variants_and_unique_gtins(self):
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        self.assertEqual(len(gtins), len(set(gtins)))
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                matches = [v for v in self.variants if v.get("variant_id") == expected["variant_id"]]
                self.assertEqual(len(matches), 1)
                variant = matches[0]
                self.assertEqual(variant.get("product_id"), expected["product_id"])
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("gtin"), expected["gtin"])
                self.assertEqual(variant.get("source_url"), expected["url"])
                self.assertEqual(variant.get("source_evidence_url"), expected["url"])

    def test_family_registry_is_aligned(self):
        for name, expected in EXPECTED.items():
            product = next(p for p in self.products if p.get("product_id") == expected["product_id"])
            family = self.families[product["family_id"]]
            rows = [r for r in family["products"] if r.get("canonical_name") == name]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].get("formats_ml"), [100])

    def test_catalog_identity_integrity_and_no_offer_data(self):
        pids = [p.get("product_id") for p in self.products]
        vids = [v.get("variant_id") for v in self.variants]
        known = set(pids)
        self.assertEqual(len(pids), len(set(pids)))
        self.assertEqual(len(vids), len(set(vids)))
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))
        forbidden = {"price", "currency", "availability", "stock", "shipping_cost", "retailer", "offer_url"}
        selected = {v["product_id"] for v in EXPECTED.values()}
        for variant in self.variants:
            if variant.get("product_id") in selected:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()
