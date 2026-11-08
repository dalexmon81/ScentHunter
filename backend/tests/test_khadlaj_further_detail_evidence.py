"""Further official Khadlaj product-detail evidence regression tests."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
DETAILS = {
    "Sueno": ("https://khadlaj-perfumes.com/collections/deals/products/sueno-100ml-extrait-de-parfum-for-women", 100, "Extrait de Parfum"),
    "Saraya": ("https://khadlaj-perfumes.com/products/khadlaj-saraya-60-ml-extrait-de-parfum-spray-for-men-women", 60, "Extrait de Parfum"),
    "Strawberry Shake": ("https://khadlaj-perfumes.com/products/strawberry-shake-eau-de-parfum-spray-for-women-dubai-uae-online", 100, "Eau de Parfum"),
    "Mansion": ("https://khadlaj-perfumes.com/products/mansion-eau-de-parfum-spray-for-unisex-scents-by-khadlaj-dubai-uae", 100, "Eau de Parfum"),
    "Peach Velvet": ("https://khadlaj-perfumes.com/products/peach-velvet-100-ml-extrait-de-parfum-for-women-top-women-fragrance-brand-uae", 100, "Extrait de Parfum"),
    "Zayaan Gold": ("https://khadlaj-perfumes.com/products/zayaan-gold-100-ml-eau-de-parfum-for-men", 100, "Eau de Parfum"),
}


class KhadlajFurtherDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [p for p in cls.catalog["products"] if p.get("brand") == "Khadlaj"]
        cls.variants = cls.catalog["variants"]

    def test_six_existing_identities_have_official_detail_evidence(self):
        for name, (url, size, concentration) in DETAILS.items():
            with self.subTest(product=name):
                matches = [p for p in self.products if p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("concentration"), concentration)
                variants = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == size
                    and v.get("concentration") == concentration
                ]
                self.assertEqual(len(variants), 1)

    def test_canonical_catalog_size_is_unchanged(self):
        self.assertEqual(len(self.catalog["products"]), 2061)
        self.assertEqual(len(self.products), 116)


if __name__ == "__main__":
    unittest.main()
