"""Official Ministry of Oud product-detail reconciliation for Paris Corner."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Ministry of Oud - Amber Oud": (
        "SH-PARIS-CORNER-MINISTRY-OF-OUD-AMBER-OUD",
        "https://www.pariscornerperfumes.com/products/ministry-of-oud-amber-oud",
        "Eau de Parfum",
    ),
    "Ministry of Oud - Oud Indonesian": (
        "SH-PARIS-CORNER-MINISTRY-OF-OUD-OUD-INDONESIAN",
        "https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-indonesian",
        "Eau de Parfum",
    ),
    "Ministry of Oud - Oud Royal": (
        "SH-PARIS-CORNER-MINISTRY-OF-OUD-OUD-ROYAL",
        "https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-royal",
        "Eau de Parfum",
    ),
    "Ministry of Oud - Oud Satin": (
        "SH-PARIS-CORNER-MINISTRY-OF-OUD-OUD-SATIN",
        "https://www.pariscornerperfumes.com/products/ministry-of-oud-oud-satin",
        None,
    ),
    "Ministry of Oud - Strictly Oud": (
        "SH-PARIS-CORNER-MINISTRY-OF-OUD-STRICTLY-OUD",
        "https://www.pariscornerperfumes.com/products/ministry-of-oud-strictly-oud",
        "Eau de Parfum",
    ),
}


class ParisCornerMinistryOfOudDetailTests(unittest.TestCase):
    def test_official_ministry_of_oud_products_are_canonical_and_source_verified(self):
        for name, (product_id, url, concentration) in EXPECTED.items():
            with self.subTest(product=name):
                matches = [
                    p for p in CATALOG["products"]
                    if p.get("brand_name") == "Paris Corner"
                    and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("product_id"), product_id)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("formats_ml"), [100])
                self.assertEqual(product.get("concentration"), concentration)

    def test_each_new_canonical_product_has_one_provenanced_100ml_variant(self):
        for name, (product_id, url, concentration) in EXPECTED.items():
            with self.subTest(product=name):
                variants = [
                    v for v in CATALOG["variants"]
                    if v.get("product_id") == product_id and v.get("size_ml") == 100
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("source_url"), url)
                self.assertEqual(variants[0].get("source_evidence_url"), url)
                self.assertEqual(variants[0].get("concentration"), concentration)

    def test_family_registry_formats_match_official_100ml_pages(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "paris_corner_catalog")
        entries = {p["canonical_name"]: p for p in family["products"]}
        for name in EXPECTED:
            with self.subTest(product=name):
                self.assertEqual(entries[name].get("formats_ml"), [100])


if __name__ == "__main__":
    unittest.main()
