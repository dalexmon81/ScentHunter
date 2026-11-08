"""Regression coverage for Maison Asrar official 100 ml EDP evidence."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Jawhara Rouge": (
        "https://maisonasrar.com/collections/jawhara-collection/products/jawhara-rouge-eau-de-perfum-100ml",
        "https://maisonasrar.com/blogs/news/experience-the-luxury-perfumes-by-maison-asrar",
    ),
    "Jawhara Black": (
        "https://maisonasrar.com/products/jawhara-black-eau-de-perfum-100ml",
        "https://maisonasrar.com/blogs/news/experience-the-luxury-perfumes-by-maison-asrar",
    ),
    "Fresh Iris": (
        "https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml",
        "https://maisonasrar.com/blogs/news/iris",
    ),
    "Dear Jasmine": (
        "https://maisonasrar.com/products/dear-jasmine-maison-asrar-eau-de-perfum-100-ml",
        "https://maisonasrar.com/blogs/news/%D8%A7%D9%84%D9%8A%D8%A7%D8%B3%D9%85%D9%8A%D9%86",
    ),
}


class MaisonAsrarOfficialBlogVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Maison Asrar"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "maison_asrar_catalog"
        )

    def test_official_product_and_brand_blog_evidence(self):
        for name, (product_url, evidence_url) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], product_url)
                self.assertEqual(product["source_evidence_url"], evidence_url)
                self.assertIn(100, product["formats_ml"])
                self.assertEqual(product["concentration"], "Eau de Parfum")
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                    and v.get("concentration") == "Eau de Parfum"
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["source_url"], product_url)

    def test_family_registry_formats_are_aligned(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                product = next(p for p in self.family["products"] if p["canonical_name"] == name)
                self.assertIn(100, product.get("formats_ml", []))

    def test_variant_ids_are_unique_and_parent_products_exist(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))


if __name__ == "__main__":
    unittest.main()
