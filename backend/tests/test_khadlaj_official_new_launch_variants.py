"""Regression coverage for Khadlaj new-launch variants from official product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Onyx Galaxy": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men"),
    "Island Sun": (100, "Extrait de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-island-sun-100-ml-extrait-de-parfum"),
    "Sueno": (100, "Extrait de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/sueno-100ml-extrait-de-parfum-for-women"),
    "Saraya": (60, "Extrait de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women"),
    "Zayaan Silver": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men"),
    "Qarar": (60, "Extrait de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum"),
    "Ihthiraam": (60, "Extrait de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/ihthraam-extrait-de-parfum-spray-oriental-unisex-fragrance"),
    "Icon": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-icon-100-ml-eau-de-parfum-spray-for-men"),
    "Panache Angel Dust": (100, "Extrait de Parfum", "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/panache-angel-dust-100-ml-extrait-de-parfum-spray-for-women-shop-online-dubai-uae"),
}


class KhadlajOfficialNewLaunchVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Khadlaj"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "khadlaj_catalog"
        )

    def test_official_product_page_and_variant_evidence(self):
        for name, (size, concentration, url) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["formats_ml"], [size])
                self.assertEqual(product["concentration"], concentration)
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == size
                    and v.get("concentration") == concentration
                ]
                self.assertEqual(len(matches), 1)

    def test_family_registry_formats_match_verified_variants(self):
        for name, (size, _concentration, _url) in EXPECTED.items():
            with self.subTest(product=name):
                registry_product = next(
                    p for p in self.family["products"]
                    if p["canonical_name"] == name
                )
                self.assertIn(size, registry_product.get("formats_ml", []))

    def test_variant_ids_remain_unique_and_refer_to_existing_products(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))


if __name__ == "__main__":
    unittest.main()
