"""Official Khadlaj product-detail evidence regression tests."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
DETAILS = {
    "Island Dreams": "https://khadlaj-perfumes.com/collections/all/products/island-dreams-100-ml-extrait-de-parfum",
    "Panache Angel Dust": "https://khadlaj-perfumes.com/collections/all/products/panache-angel-dust-100-ml-extrait-de-parfum-spray-for-women-shop-online-dubai-uae",
    "Cream Velvet": "https://khadlaj-perfumes.com/collections/all/products/cream-velvet-100-ml-extrait-de-parfum-for-women-best-perfumes",
    "Fursan White": "https://khadlaj-perfumes.com/collections/all/products/khadlaj-fursan-white-100-ml-edp-spray-perfume-for-women-best-price-in-dubai-uae",
    "Cloud Candy": "https://khadlaj-perfumes.com/collections/all/products/cloud-candy-100-ml-extrait-de-parfum-fruity-marshmallow-fragrance-for-women-to-shop-online-in-dubai-uae",
    "Sawaar Vanille Blanc": "https://khadlaj-perfumes.com/products/sawaar-vanille-blanc-100-ml-eau-de-parfum-spray-for-women",
}
CONCENTRATIONS = {
    "Island Dreams": "Extrait de Parfum",
    "Panache Angel Dust": "Extrait de Parfum",
    "Cream Velvet": "Extrait de Parfum",
    "Fursan White": "Eau de Parfum",
    "Cloud Candy": "Extrait de Parfum",
}


class KhadlajDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = [
            p for p in cls.catalog["products"]
            if p.get("brand") == "Khadlaj"
        ]
        cls.variants = cls.catalog["variants"]

    def product(self, name):
        matches = [p for p in self.products if p.get("canonical_name") == name]
        self.assertEqual(len(matches), 1, name)
        return matches[0]

    def test_six_existing_identities_have_official_detail_evidence(self):
        for name, url in DETAILS.items():
            with self.subTest(product=name):
                product = self.product(name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)

    def test_detail_pages_support_exact_100ml_concentration_variants(self):
        for name, concentration in CONCENTRATIONS.items():
            with self.subTest(product=name):
                product = self.product(name)
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("concentration"), concentration)
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == 100
                    and v.get("concentration") == concentration
                ]
                self.assertEqual(len(matches), 1)

    def test_sawaar_size_is_retained_but_conflicting_concentration_is_not_inferred(self):
        product = self.product("Sawaar Vanille Blanc")
        self.assertEqual(product.get("identity_status"), "source_verified_name")
        self.assertEqual(product.get("formats_ml"), [100])
        self.assertNotIn("concentration", product)
        matches = [
            v for v in self.variants
            if v.get("product_id") == product["product_id"]
            and v.get("size_ml") == 100
        ]
        self.assertEqual(len(matches), 1)
        self.assertNotIn("concentration", matches[0])


if __name__ == "__main__":
    unittest.main()
