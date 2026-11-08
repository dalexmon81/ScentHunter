"""Official product-page evidence for five additional Armaf fragrances."""

import json
import unittest
import unicodedata
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG_PATH = BACKEND / "product_catalog.json"
REGISTRY_PATH = BACKEND / "family_registry.json"

PRODUCTS = {
    "Check Mate White - Knight": {
        "url": "https://cz.armaf.eu/en/products/check-mate-white-knight",
        "sizes": [100],
    },
    "Odyssey French Kiss": {
        "url": "https://cz.armaf.eu/products/odyssey-french-kiss",
        "sizes": [60],
    },
    "Odyssey Tyrant Special Edition": {
        "url": "https://cz.armaf.eu/en/products/odyssey-tyrant-special-edition",
        "sizes": [60, 100],
    },
    "Odyssey Eau de Montagne Mountain Edition": {
        "url": "https://cz.armaf.eu/en/products/odyssey-eau-de-montagne-mountain-edition",
        "sizes": [100],
    },
    "Dubai Delicacy Kunafa Chocolate": {
        "url": "https://cz.armaf.eu/products/dubai-delicacy",
        "sizes": [70],
    },
}


def normalized(value):
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


class ArmafOfficialFragranceAdditionsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        cls.products = cls.catalog["products"]
        cls.variants = cls.catalog["variants"]
        cls.armaf_family = next(
            family for family in cls.registry["families"]
            if family["family_id"] == "armaf_catalog"
        )

    def test_products_are_unique_and_individually_source_verified(self):
        for name, evidence in PRODUCTS.items():
            with self.subTest(product=name):
                matches = [
                    product for product in self.products
                    if product.get("brand") == "Armaf"
                    and normalized(product.get("canonical_name")) == normalized(name)
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), evidence["url"])
                self.assertEqual(product.get("source_evidence_url"), evidence["url"])
                self.assertEqual(product.get("formats_ml"), evidence["sizes"])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")

    def test_explicit_variants_match_the_documented_sizes(self):
        for name, evidence in PRODUCTS.items():
            product = next(
                product for product in self.products
                if product.get("brand") == "Armaf"
                and normalized(product.get("canonical_name")) == normalized(name)
            )
            variants = [
                variant for variant in self.variants
                if variant.get("product_id") == product["product_id"]
            ]
            self.assertEqual(sorted(v["size_ml"] for v in variants), sorted(evidence["sizes"]))
            self.assertTrue(all(v.get("source_url") == evidence["url"] for v in variants))
            self.assertTrue(all(v.get("concentration") == "Eau de Parfum" for v in variants))

    def test_family_registry_covers_each_new_canonical_identity(self):
        family_products = self.armaf_family["products"]
        for name in PRODUCTS:
            with self.subTest(product=name):
                matches = [
                    product for product in family_products
                    if normalized(product.get("canonical_name")) == normalized(name)
                ]
                self.assertEqual(len(matches), 1)

    def test_no_duplicate_product_or_variant_ids(self):
        product_ids = [product["product_id"] for product in self.products]
        variant_ids = [variant["variant_id"] for variant in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
