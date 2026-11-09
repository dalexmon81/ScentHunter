"""Official detail-page evidence for selected Swiss Arabian fragrances."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
EXPECTED = {
    "Shaghaf Oud": ("https://us.swissarabian.com/products/shaghaf-oud-3", 75, "Eau de Parfum"),
    "Casablanca": ("https://us.swissarabian.com/products/casablanca", 100, "Eau de Parfum"),
    "Primal Code": ("https://us.swissarabian.com/products/primal-code", 100, "Eau de Parfum"),
    "Valencia": ("https://de.swissarabian.com/en/collections/perfumes/products/valencia", None, "Eau de Parfum"),
    "Shaghaf Oud Marine": ("https://swissarabian.com/collections/new-launches/products/shaghaf-oud-marine", 75, "Eau de Parfum"),
    "Echoes of St. Moritz": ("https://swissarabian.com/collections/new-launches/products/echoes-of-st-moritz", 100, "Extrait de Parfum"),
    "Shaghaf Nectar Blush": ("https://us.swissarabian.com/collections/new-launches/products/shaghaf-nectar-blush", 75, "Eau de Parfum"),
    "Patchouli 01": ("https://us.swissarabian.com/products/patchouli-01", 50, "Extrait de Parfum"),
    "Enigma of Taif": ("https://swissarabian.com/collections/new-launches/products/enigma-of-taif", 100, None),
    "Shaghaf Amber Infusion": ("https://swissarabian.com/collections/new-launches/products/shaghaf-amber-infusion", 75, "Extrait de Parfum"),
    "Soul of Bali": ("https://swissarabian.com/collections/new-launches/products/soul-of-bali", 100, "Extrait de Parfum"),
    "Vanilla 01": ("https://us.swissarabian.com/products/vanilla-01", 50, "Extrait de Parfum"),
    "Tobacco 01": ("https://us.swissarabian.com/products/tobacco-01", 50, "Extrait de Parfum"),
}


class SwissArabianDetailEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with CATALOG_PATH.open(encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]

    def test_all_identities_have_official_detail_evidence(self):
        for name, (url, size, concentration) in EXPECTED.items():
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
                self.assertEqual(product.get("concentration"), concentration)
                if size:
                    self.assertIn(size, product.get("formats_ml", []))

    def test_explicit_sizes_have_matching_variants(self):
        for name, (_, size, concentration) in EXPECTED.items():
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
                self.assertEqual(variants[0].get("concentration"), concentration)


if __name__ == "__main__":
    unittest.main()
