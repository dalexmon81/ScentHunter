"""Regression coverage for the eight individually verified launches added on 2026-11-09."""
import json
import unittest
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "product_catalog.json"
with CATALOG_PATH.open(encoding="utf-8") as handle:
    CATALOG = json.load(handle)

EXPECTED = {
    ("Gulf Orchid", "Ameer"): (
        "https://shop-gulforchid.com/products/ameer",
        "Eau de Parfum",
        100,
        None,
    ),
    ("Gulf Orchid", "Belle"): (
        "https://shop-gulforchid.com/products/belle",
        "Eau de Parfum",
        100,
        None,
    ),
    ("Gulf Orchid", "Amour"): (
        "https://shop-gulforchid.com/products/amour",
        "Eau de Parfum",
        100,
        None,
    ),
    ("Gulf Orchid", "Chic"): (
        "https://shop-gulforchid.com/products/chic",
        "Eau de Parfum",
        100,
        None,
    ),
    ("Maison Alhambra", "Victorioso Heroic"): (
        "https://maisonalhambra-usa.com/products/maison-alhambra-victorioso-heroic-eau-de-parfum-for-men",
        "Eau de Parfum",
        100,
        "6290362340584",
    ),
    ("Maison Alhambra", "Rose Origami"): (
        "https://maisonalhambra-usa.com/products/maison-alhambra-rose-origami-eau-de-parfum-for-everyone",
        "Eau de Parfum",
        100,
        "6290362340928",
    ),
    ("Maison Alhambra", "Opera Rouge"): (
        "https://maisonalhambra-usa.com/products/maison-alhambra-opera-rouge-eau-de-parfum-for-everyone",
        "Eau de Parfum",
        100,
        "6290362340881",
    ),
    ("Maison Alhambra", "Camille"): (
        "https://maisonalhambra-usa.com/products/maison-alhambra-camille-eau-de-parfum-for-women",
        "Eau de Parfum",
        100,
        "6290360599236",
    ),
}


class VerifiedNewLaunches20261109Tests(unittest.TestCase):
    def test_all_eight_identities_have_individual_product_page_provenance(self):
        products = CATALOG.get("products", [])
        for (brand, name), (source_url, concentration, size_ml, gtin) in EXPECTED.items():
            with self.subTest(brand=brand, name=name):
                matches = [
                    row for row in products
                    if (row.get("brand_name") or row.get("brand")) == brand
                    and (row.get("canonical_name") or row.get("name")) == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), source_url)
                self.assertEqual(product.get("concentration"), concentration)
                self.assertEqual(product.get("formats_ml"), [size_ml])
                if gtin is not None:
                    self.assertEqual(product.get("gtins"), [gtin])

    def test_each_identity_has_exactly_one_matching_variant_with_source_evidence(self):
        products = CATALOG.get("products", [])
        variants = CATALOG.get("variants", [])
        for (brand, name), (source_url, concentration, size_ml, _gtin) in EXPECTED.items():
            with self.subTest(brand=brand, name=name):
                product = next(
                    row for row in products
                    if (row.get("brand_name") or row.get("brand")) == brand
                    and (row.get("canonical_name") or row.get("name")) == name
                )
                matches = [
                    row for row in variants
                    if row.get("product_id") == product["product_id"]
                ]
                self.assertEqual(len(matches), 1)
                variant = matches[0]
                self.assertEqual(variant.get("size_ml"), size_ml)
                self.assertEqual(variant.get("concentration"), concentration)
                self.assertEqual(
                    variant.get("variant_id"),
                    f"SHV-{product['product_id']}-{size_ml}-000",
                )
                self.assertEqual(variant.get("source_evidence_url"), source_url)
                for commercial_field in ("price", "stock", "shipping_cost", "store_url"):
                    self.assertNotIn(commercial_field, variant)

    def test_new_launches_do_not_duplicate_catalog_identity_or_ids(self):
        products = CATALOG.get("products", [])
        variants = CATALOG.get("variants", [])
        requested = set(EXPECTED)
        relevant_products = [
            row for row in products
            if ((row.get("brand_name") or row.get("brand")),
                (row.get("canonical_name") or row.get("name"))) in requested
        ]
        self.assertEqual(len(relevant_products), len(EXPECTED))
        product_ids = [row.get("product_id") for row in products]
        variant_ids = [row.get("variant_id") for row in variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
