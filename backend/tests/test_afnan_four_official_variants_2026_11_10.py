"""Four Afnan bottle variants verified on official regional product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "9 AM Dive": {
        "product_id": "SH-AFNAN-9e3c80fa",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-AFNAN-9e3c80fa-100-EDP",
        "url": "https://www.de.afnan.com/en/products/9-am-dive",
    },
    "Rare Reef": {
        "product_id": "SH-AFNAN-e408d61b",
        "size_ml": 100,
        "concentration": "Extrait de Parfum",
        "variant_id": "SHV-SH-AFNAN-e408d61b-100-EXTRAIT",
        "url": "https://www.at.afnan.com/en/products/rare-reef",
    },
    "Turathi Brown Homme": {
        "product_id": "SH-AFNAN-5cdc0bae",
        "size_ml": 90,
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-AFNAN-5cdc0bae-90-EDP",
        "url": "https://www.at.afnan.com/en/products/turathi-brown-homme",
    },
    "Historic Olmeda": {
        "product_id": "SH-AFNAN-62b409e4",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "variant_id": "SHV-SH-AFNAN-62b409e4-100-EDP",
        "url": "https://www.at.afnan.com/products/historic-olmeda",
    },
}


class AfnanFourOfficialVariantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(
            family for family in REGISTRY["families"]
            if family.get("family_id") == "afnan_catalog"
        )

    def test_existing_canonical_products_have_official_variants(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = next(
                    p for p in self.products
                    if p.get("product_id") == expected["product_id"]
                )
                self.assertEqual(product["brand"], "Afnan")
                self.assertEqual(product["canonical_name"], name)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["url"])
                self.assertEqual(product["formats_ml"], [expected["size_ml"]])
                self.assertEqual(product["concentration"], expected["concentration"])

                variants = [
                    v for v in self.variants
                    if v.get("product_id") == expected["product_id"]
                ]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["variant_id"], expected["variant_id"])
                self.assertEqual(variant["size_ml"], expected["size_ml"])
                self.assertEqual(variant["concentration"], expected["concentration"])
                self.assertEqual(variant["source_evidence_url"], expected["url"])
                self.assertNotIn("gtin", variant)

    def test_afnan_family_registry_formats_match_the_verified_variants(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [
                    item for item in self.family["products"]
                    if item.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [expected["size_ml"]])

    def test_global_catalog_integrity_and_offer_separation(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        tuples = [
            (v.get("product_id"), v.get("size_ml"), v.get("concentration"))
            for v in self.variants
        ]
        known_products = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertEqual(len(tuples), len(set(tuples)))
        self.assertTrue(all(v.get("product_id") in known_products for v in self.variants))
        offer_fields = {"price", "stock", "availability", "shipping_cost", "store_url", "retailer"}
        for variant in self.variants:
            self.assertTrue(offer_fields.isdisjoint(variant))


if __name__ == "__main__":
    unittest.main()
