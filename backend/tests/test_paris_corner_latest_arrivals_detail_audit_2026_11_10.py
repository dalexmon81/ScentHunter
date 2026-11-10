"""Paris Corner official latest-arrival detail-page regression coverage."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Zariya": (
        "SH-PARIS-CORNER-ZARIYA",
        "https://www.pariscornerperfumes.com/products/zariya",
        "Eau de Parfum",
    ),
    "Green Bet": (
        "SH-PARIS-CORNER-GREEN-BET",
        "https://www.pariscornerperfumes.com/products/green-bet",
        None,
    ),
    "Heer": (
        "SH-PARIS-CORNER-HEER",
        "https://www.pariscornerperfumes.com/products/heer",
        None,
    ),
    "The Show Magnifique": (
        "SH-PARIS-CORNER-THESHOWMAGNIFIQUE",
        "https://www.pariscornerperfumes.com/products/the-show-magnifique",
        None,
    ),
    "Lueur d'Espoir Memories of Summer": (
        "SH-PARIS-CORNER-LUEUR-D-ESPOIR-MEMORIES-OF-SUMMER",
        "https://www.pariscornerperfumes.com/products/lueur-d-espoir-memories-of-summer",
        None,
    ),
}


class ParisCornerLatestArrivalsDetailAuditTests(unittest.TestCase):
    def test_official_detail_pages_map_to_existing_canonical_products(self):
        for name, (product_id, url, concentration) in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    product for product in CATALOG["products"]
                    if product.get("brand_name") == "Paris Corner"
                    and product.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("concentration"), concentration)

    def test_each_product_has_one_official_100ml_variant(self):
        for name, (product_id, url, concentration) in EXPECTED.items():
            with self.subTest(product=name):
                variants = [
                    variant for variant in CATALOG["variants"]
                    if variant.get("product_id") == product_id
                    and variant.get("size_ml") == 100
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(
                    variants[0].get("source_evidence_url") or variants[0].get("source_url"),
                    url,
                )
                self.assertEqual(variants[0].get("concentration"), concentration)

    def test_family_registry_contains_each_official_product_and_size(self):
        family = next(
            row for row in REGISTRY["families"]
            if row.get("family_id") == "paris_corner_catalog"
        )
        entries = {
            row.get("canonical_name"): row
            for row in family.get("products", [])
        }
        for name in EXPECTED:
            with self.subTest(product=name):
                self.assertIn(name, entries)
                self.assertIn(100, entries[name].get("formats_ml", []))


if __name__ == "__main__":
    unittest.main()
