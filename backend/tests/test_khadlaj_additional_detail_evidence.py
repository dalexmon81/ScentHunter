"""Additional official Khadlaj product-detail evidence regression tests."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
DETAILS = {
    "Onyx Galaxy": ("https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men", 100, None),
    "Muse": ("https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women", 100, "Eau de Parfum"),
    "Zayaan Silver": ("https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/zayaan-silver-fresh-aquatic-spicy-woody-eau-de-parfum-for-men", 100, "Eau de Parfum"),
    "Qarar": ("https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-qarar-unisex-bold-oriental-extrait-de-parfum", 60, "Extrait de Parfum"),
    "Ihthiraam": ("https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/ihthraam-extrait-de-parfum-spray-oriental-unisex-fragrance", 60, "Extrait de Parfum"),
    "Icon": ("https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-icon-100-ml-eau-de-parfum-spray-for-men", 100, "Eau de Parfum"),
}


class KhadlajAdditionalDetailEvidenceTests(unittest.TestCase):
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
        for name, (url, size, concentration) in DETAILS.items():
            with self.subTest(product=name):
                product = self.product(name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("formats_ml"), [size])
                if concentration:
                    self.assertEqual(product.get("concentration"), concentration)
                else:
                    self.assertNotIn("concentration", product)

    def test_variants_match_only_explicit_official_sizes_and_concentrations(self):
        for name, (_, size, concentration) in DETAILS.items():
            with self.subTest(product=name):
                product = self.product(name)
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product["product_id"]
                    and v.get("size_ml") == size
                ]
                self.assertEqual(len(matches), 1)
                if concentration:
                    self.assertEqual(matches[0].get("concentration"), concentration)
                else:
                    self.assertNotIn("concentration", matches[0])

    def test_no_new_canonical_identities_are_created(self):
        self.assertEqual(len(self.catalog["products"]), 2061)
        self.assertEqual(len(self.products), 116)


if __name__ == "__main__":
    unittest.main()
