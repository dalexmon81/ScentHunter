"""Regression tests for Khadlaj identities verified against official product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Bleu Glace": (100, "Extrait de Parfum", "https://khadlaj-perfumes.com/products/bleu-glace-100-ml-extrait-de-parfum-for-men-fresh-fragrance-online-dubai-uae"),
    "Code Viola Nectar": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/products/code-viola-nectar-spray-shop-online-best-price-in-dubai-uae"),
    "Desert Rose": (100, "Extrait de Parfum", "https://khadlaj-perfumes.com/products/desert-rose-100-ml-extrait-de-parfum-for-women-fragrance-to-shop-online-dubai-uae"),
    "Gaith": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/products/gaith-100-ml-edp-spray-men-perfumes-dubai-uae"),
    "Mocha Latte": (100, "Extrait de Parfum", "https://khadlaj-perfumes.com/products/mocha-latte-100-ml-extrait-de-parfum-spray-for-unisex-coffee-fragrance-dubai-uae"),
    "Rasayel Shagaf": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/products/rasayel-shagaf-100-ml-edp-de-parfum-spray-for-men"),
    "Rasayel Vid": (100, "Extrait de Parfum", "https://khadlaj-perfumes.com/products/rasayel-vid-100-ml-extrait-de-parfum-spray-copy"),
    "Rose And Romance": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/products/rose-and-romance-spray-shop-online-best-price-in-dubai-uae"),
    "Uno Sensuale": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/products/uno-sensuale-edp-spray-shop-online-best-price-in-dubai-uae"),
    "Wow Oud": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/products/wow-oud-100-ml-edp-spray"),
    "Ghadeer Gold": (100, "Eau de Parfum", "https://khadlaj-perfumes.com/products/ghadeer-gold-100-ml-edp-spray-for-women-best-price-perfume-online-dubai-uae"),
    "Nuha": (85, "Eau de Parfum", "https://khadlaj-perfumes.com/products/nuha-85-ml-edp-spray-perfume-for-women-dubai-uae"),
}

class KhadlajOfficialDetailTests(unittest.TestCase):
    def test_twelve_official_detail_page_products_and_variants(self):
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Khadlaj"}
        variants = CATALOG["variants"]
        for name, (size, concentration, source) in EXPECTED.items():
            with self.subTest(name=name):
                product = products[name]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source)
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("concentration"), concentration)
                matched = [v for v in variants if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(matched), 1)
                self.assertEqual(matched[0].get("size_ml"), size)
                self.assertEqual(matched[0].get("concentration"), concentration)
        self.assertIn("Rose & Romance", products["Rose And Romance"].get("aliases", []))

if __name__ == "__main__":
    unittest.main()
