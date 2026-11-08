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

ADDITIONAL_IDENTITY_URLS = {
    "Jawhara Rouge": "https://maisonasrar.com/products/jawhara-rouge-eau-de-perfum-100ml",
    "Jawhara Black": "https://maisonasrar.com/products/jawhara-black-eau-de-perfum-100ml",
    "Petra": "https://maisonasrar.com/products/petra-maison-asrar-eau-de-perfum-100ml",
    "Casablanca": "https://maisonasrar.com/products/casablanca-maison-asrar-eau-de-perfum-100ml",
    "Trophy": "https://maisonasrar.com/products/trophy-eau-de-perfum-100ml",
    "Oscar": "https://maisonasrar.com/products/oscar-eau-de-perfum-100ml",
    "Fairy Tale": "https://maisonasrar.com/products/fairy-tale-eau-de-perfum-100ml",
    "Magic Night": "https://maisonasrar.com/products/magic-night-eau-de-perfum-100ml",
    "Icon": "https://maisonasrar.com/products/icon-eau-de-perfum-100ml",
    "Desire": "https://maisonasrar.com/products/desire-eau-de-perfum-100ml",
}

LOCK_KEY = {
    "Plot Twist": "https://shop-gulforchid.com/products/plot-twist",
    "Love Key": "https://shop-gulforchid.com/products/love-key",
    "Unsolved Mystery": "https://shop-gulforchid.com/products/unsolved-mystery",
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



    def test_additional_existing_identities_have_official_detail_page_evidence_only(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Maison Asrar"
        }
        variants = CATALOG.get("variants", [])
        for name, url in ADDITIONAL_IDENTITY_URLS.items():
            product = products[name]
            with self.subTest(product=name):
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertNotIn("formats_ml", product)
                self.assertEqual(
                    [row for row in variants if row.get("product_id") == product.get("product_id")],
                    [],
                )

    def test_lock_and_key_products_keep_gulf_orchid_brand_and_variant_evidence(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Maison Asrar"
        }
        variants = CATALOG.get("variants", [])
        for name, url in LOCK_KEY.items():
            product = products[name]
            matching = [
                row for row in variants
                if row.get("product_id") == product.get("product_id")
                and row.get("size_ml") == 100
            ]
            with self.subTest(product=name):
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(len(matching), 1)
                self.assertEqual(matching[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(matching[0].get("source_evidence_url"), url)

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
