"""Maison Alhambra official product-page validation for Jean Lowe variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Jean Lowe Immortal": {
        "product_id": "SH-MAISON-ALHAMBRA-14a18233",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-14a18233-100-000",
        "gtin": "6291108735541",
        "gender": "Men",
        "url": "https://maisonalhambra-usa.com/products/maison-alhambra-jean-lowe-immortal-eau-de-parfum-for-men",
    },
    "Jean Lowe Fraiche": {
        "product_id": "SH-MAISON-ALHAMBRA-7bf23686",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-7bf23686-100-000",
        "gtin": "6291108735565",
        "gender": "Unisex",
        "url": "https://maisonalhambra-usa.com/products/maison-alhambra-jean-lowe-fraiche-eau-de-parfum-for-everyone",
    },
}


class MaisonAlhambraJeanLoweOfficialVariantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_existing_canonical_products_are_verified_without_new_ids(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [
                    p for p in self.products
                    if p.get("brand_name", p.get("brand")) == "Maison Alhambra"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(rows), 1)
                product = rows[0]
                self.assertEqual(product.get("product_id"), expected["product_id"])
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), expected["url"])
                self.assertEqual(product.get("source_product_url"), expected["url"])
                self.assertEqual(product.get("source_evidence_url"), expected["url"])
                self.assertEqual(product.get("gender"), expected["gender"])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("gtins"), [expected["gtin"]])

    def test_100ml_edp_variants_have_official_sources_and_unique_gtins(self):
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        self.assertEqual(len(gtins), len(set(gtins)))
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [v for v in self.variants if v.get("variant_id") == expected["variant_id"]]
                self.assertEqual(len(rows), 1)
                variant = rows[0]
                self.assertEqual(variant.get("product_id"), expected["product_id"])
                self.assertEqual(variant.get("size_ml"), 100)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("gtin"), expected["gtin"])
                self.assertEqual(variant.get("source_url"), expected["url"])
                self.assertEqual(variant.get("source_evidence_url"), expected["url"])

    def test_family_registry_matches_canonical_product_formats(self):
        for name, expected in EXPECTED.items():
            product = next(p for p in self.products if p.get("product_id") == expected["product_id"])
            family = self.families[product["family_id"]]
            rows = [r for r in family["products"] if r.get("canonical_name") == name]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].get("formats_ml"), [100])

    def test_no_identity_duplicates_or_orphan_variants(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        known = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))

    def test_no_retail_offer_fields_are_imported(self):
        forbidden = {"price", "currency", "availability", "stock", "shipping_cost", "retailer", "offer_url"}
        parent_ids = {value["product_id"] for value in EXPECTED.values()}
        for variant in self.variants:
            if variant.get("product_id") in parent_ids:
                self.assertFalse(forbidden.intersection(variant))


if __name__ == "__main__":
    unittest.main()
