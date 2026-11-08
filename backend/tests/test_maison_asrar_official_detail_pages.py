"""Regression tests for Maison Asrar official fragrance detail pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
FAMILY_REGISTRY = json.loads(
    (BACKEND / "family_registry.json").read_text(encoding="utf-8")
)

EXPECTED = {
    "Bloom Bloom": (
        "https://maisonasrar.com/products/bloom-bloom-eau-de-parfum-100ml", 100
    ),
    "Lolita": (
        "https://maisonasrar.com/products/lolita-eau-de-parfum-100ml", 100
    ),
    "Bonita": (
        "https://maisonasrar.com/products/bonita-eau-de-parfum-100ml", 100
    ),
    "Lily": (
        "https://maisonasrar.com/products/lily-eau-de-parfum-100ml", 100
    ),
    "Kiss My Lips": (
        "https://maisonasrar.com/products/kiss-my-lips-maison-asrar-eau-de-perfum-90ml", 90
    ),
    "Never Forget Me": (
        "https://maisonasrar.com/products/never-forget-me-maison-asrar-eau-de-perfum-90ml", 90
    ),
    "Night in Paris": (
        "https://maisonasrar.com/products/night-in-paris-maison-asrar-eau-de-perfum-90ml", 90
    ),
    "Sunset in Capri": (
        "https://maisonasrar.com/products/sunset-in-capri-maison-asrar-eau-de-perfum-90ml", 90
    ),
    "Dear Jasmine": (
        "https://maisonasrar.com/products/dear-jasmine-maison-asrar-eau-de-perfum-100-ml", 100
    ),
    "Patchouli with Love": (
        "https://maisonasrar.com/products/patchouli-with-love-maison-asrar-eau-de-perfum-100-ml", 100
    ),
    "Fresh Iris": (
        "https://maisonasrar.com/products/fresh-iris-maison-asrar-eau-de-perfum-100-ml", 100
    ),
    "Vanilla Rouge": (
        "https://maisonasrar.com/products/vanilla-rouge-maison-asrar-eau-de-perfum-100-ml", 100
    ),
}


class MaisonAsrarOfficialFragranceTests(unittest.TestCase):
    def test_existing_identities_use_official_individual_product_pages(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Maison Asrar"
        }
        for name, (url, _size) in EXPECTED.items():
            with self.subTest(product=name):
                product = products.get(name)
                self.assertIsNotNone(product, "missing canonical identity")
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)

    def test_verified_sizes_are_synced_to_family_registry(self):
        family = next(
            row for row in FAMILY_REGISTRY.get("families", [])
            if row.get("brand") == "Maison Asrar"
        )
        registry_products = {
            row.get("canonical_name"): row for row in family.get("products", [])
        }
        for name, (_url, size) in EXPECTED.items():
            with self.subTest(product=name):
                self.assertEqual(registry_products[name].get("formats_ml"), [size])

    def test_explicit_edp_size_variants_are_present_once_with_detail_evidence(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Maison Asrar"
        }
        variants = CATALOG.get("variants", [])
        variant_ids = [row.get("variant_id") for row in variants]
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        for name, (url, size) in EXPECTED.items():
            product = products[name]
            matching = [
                row for row in variants
                if row.get("product_id") == product.get("product_id")
                and row.get("size_ml") == size
            ]
            with self.subTest(product=name):
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(matching[0].get("source_evidence_url"), url)


if __name__ == "__main__":
    unittest.main()
