"""Khadlaj GTIN/gender audit; retain unspecified concentration where official pages conflict."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Onyx Galaxy": {
        "product_id": "SH-KHADLAJ-ONYX-GALAXY",
        "variant_id": "SHV-SH-KHADLAJ-ONYX-GALAXY-100-EDP",
        "url": "https://khadlaj-perfumes.com/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men",
        "size": 100, "concentration": "Eau de Parfum", "gender": "Men",
        "gtin": "6298043072762",
    },
    "Shiyaaka Snow": {
        "product_id": "SH-KHADLAJ-bbb43d66",
        "variant_id": "SHV-SH-KHADLAJ-bbb43d66-100-000",
        "url": "https://khadlaj-perfumes.com/products/special-edition-shiyaaka-snow-100-ml-eau-de-parfum-for-men",
        "size": 100, "concentration": "Eau de Parfum", "gender": "Men",
        "gtin": "6291107979335",
    },
    "Panache Angel Dust": {
        "product_id": "SH-KHADLAJ-f26d9535",
        "variant_id": "SHV-SH-KHADLAJ-f26d9535-100-000",
        "url": "https://khadlaj-perfumes.com/products/panache-angel-dust-100-ml-extrait-de-parfum-spray-for-women-shop-online-dubai-uae",
        "size": 100, "concentration": "Extrait de Parfum", "gender": "Women",
        "gtin": "6298043070829",
    },
    "Sawaar Vanille Blanc": {
        "product_id": "SH-KHADLAJ-24969f48",
        "variant_id": "SHV-SH-KHADLAJ-24969f48-100-UNSPECIFIED",
        "url": "https://khadlaj-perfumes.com/products/sawaar-vanille-blanc-100-ml-eau-de-parfum-spray-for-women",
        "size": 100, "concentration": None, "gender": "Women",
        "gtin": "6298043070768",
    },
}


class KhadlajOfficialNewLaunchCompletenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_existing_product_and_variant_ids_are_preserved(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                products = [
                    p for p in self.products
                    if p.get("brand", p.get("brand_name")) == "Khadlaj"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product["product_id"], expected["product_id"])
                variants = [v for v in self.variants if v["product_id"] == product["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["variant_id"], expected["variant_id"])

    def test_official_page_attributes_gtins_and_registry_are_aligned(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p.get("product_id") == expected["product_id"])
                variant = next(v for v in self.variants if v.get("variant_id") == expected["variant_id"])
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                for field in ("source_url", "source_product_url", "source_evidence_url"):
                    self.assertEqual(product.get(field), expected["url"])
                self.assertEqual(product.get("formats_ml"), [expected["size"]])
                self.assertEqual(product.get("gender"), expected["gender"])
                self.assertEqual(variant.get("size_ml"), expected["size"])
                self.assertEqual(variant.get("gender"), expected["gender"])
                self.assertEqual(variant.get("source_url"), expected["url"])
                self.assertEqual(variant.get("source_evidence_url"), expected["url"])
                self.assertEqual(variant.get("gtin"), expected["gtin"])
                if expected["concentration"] is None:
                    self.assertNotIn("concentration", product)
                    self.assertNotIn("concentration", variant)
                else:
                    self.assertEqual(product.get("concentration"), expected["concentration"])
                    self.assertEqual(variant.get("concentration"), expected["concentration"])
                family = self.families[product["family_id"]]
                rows = [r for r in family["products"] if r.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [expected["size"]])

    def test_global_product_variant_gtin_and_parent_integrity(self):
        product_ids = [p["product_id"] for p in self.products]
        variant_ids = [v["variant_id"] for v in self.variants]
        gtins = [v["gtin"] for v in self.variants if v.get("gtin")]
        tuples = [(v["product_id"], v.get("size_ml"), v.get("concentration")) for v in self.variants]
        known_products = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertEqual(len(tuples), len(set(tuples)))
        self.assertTrue(all(v["product_id"] in known_products for v in self.variants))

    def test_canonical_variants_do_not_contain_commercial_offer_fields(self):
        forbidden = {"price", "price_eur", "stock", "availability", "shipping_cost",
                     "store_url", "retailer_url", "offer_url", "merchant"}
        for variant in self.variants:
            with self.subTest(variant=variant.get("variant_id")):
                self.assertTrue(forbidden.isdisjoint(variant.keys()))


if __name__ == "__main__":
    unittest.main()
