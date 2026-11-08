"""Official detail-page evidence for selected Swiss Arabian fragrances."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Shaghaf Oud": ("https://us.swissarabian.com/products/shaghaf-oud-3", 75),
    "Casablanca": ("https://us.swissarabian.com/products/casablanca", 100),
    "Primal Code": ("https://us.swissarabian.com/products/primal-code", 100),
    "Valencia": ("https://de.swissarabian.com/en/collections/perfumes/products/valencia", None),
}


class SwissArabianDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_four_identities_have_official_detail_evidence(self):
        for name, (url, size) in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    p for p in self.products
                    if p.get("brand_name") == "Swiss Arabian"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                if size:
                    self.assertIn(size, product.get("formats_ml", []))

    def test_explicit_sizes_have_matching_edp_variants(self):
        for name, (_, size) in EXPECTED.items():
            if size is None:
                continue
            with self.subTest(product=name):
                product = next(
                    p for p in self.products
                    if p.get("brand_name") == "Swiss Arabian"
                    and p.get("canonical_name") == name
                )
                variants = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == size
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")


if __name__ == "__main__":
    unittest.main()
