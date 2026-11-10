"""Official-source verification for two existing Jean Lowe canonical variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Jean Lowe Azure": {
        "product_id": "SH-MAISON-ALHAMBRA-81a36e31",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-81a36e31-100-000",
        "gtin": "6290362340546",
        "url": "https://maisonalhambra-usa.com/products/maison-alhambra-jean-lowe-azure-eau-de-parfum-for-everyone",
    },
    "Jean Lowe Noir": {
        "product_id": "SH-MAISON-ALHAMBRA-68802b72",
        "variant_id": "SHV-SH-MAISON-ALHAMBRA-68802b72-100-000",
        "gtin": "6291108735534",
        "url": "https://maisonalhambra-usa.com/products/maison-alhambra-jean-lowe-noir-eau-de-parfum-for-everyone",
    },
}


class MaisonAlhambraJeanLoweAzureNoirTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_existing_products_retain_ids_and_have_official_provenance(self):
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
                self.assertEqual(product.get("gender"), "Unisex")
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("gtins"), [expected["gtin"]])

    def test_existing_variants_are_enriched_not_duplicated(self):
        all_gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        self.assertEqual(len(all_gtins), len(set(all_gtins)))
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

    def test_family_registry_matches_existing_canonical_ids(self):
        for name, expected in EXPECTED.items():
            product = next(p for p in self.products if p.get("product_id") == expected["product_id"])
            family = self.families[product["family_id"]]
            rows = [p for p in family["products"] if p.get("canonical_name") == name]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].get("formats_ml"), [100])

    def test_no_duplicate_ids_and_no_orphan_variants(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        known = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))

    def test_no_price_stock_or_offer_fields_are_added(self):
        forbidden = {"price", "currency", "availability", "stock", "shipping_cost", "retailer", "offer_url", "store_url"}
        ids = {x["product_id"] for x in EXPECTED.values()}
        for row in self.variants:
            if row.get("product_id") in ids:
                self.assertFalse(forbidden.intersection(row))


if __name__ == "__main__":
    unittest.main()
