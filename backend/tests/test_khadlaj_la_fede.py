"""Regression tests for individually verified Khadlaj La Fede identities.

The family registry contains a broader 36-name discovery list. Only names with
individual official product-detail evidence are promoted into the canonical
seed by this test; registry-only candidates are deliberately not bulk-imported.
"""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "La Fede Intoxicate Mystique": {
        "size_ml": 100,
        "concentration": "Extrait de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes/products/la-fede-intoxicate-blue-elixir-100-ml-eau-de-parfume-spray-for-men-copy",
    },
    "La Fede Celebrity Crush": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes/products/la-fede-celebrity-crush-100ml-eau-de-parfum",
    },
    "La Fede Celebrity Fame": {
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes/products/la-fede-celebrity-fame-100ml-eau-de-parfum",
    },
}


class KhadlajLaFedeTests(unittest.TestCase):
    def setUp(self):
        self.products = [
            p for p in CATALOG["products"]
            if p.get("brand") == "Khadlaj" and p.get("family_id") == "khadlaj_la_fede"
        ]
        self.family = next(
            f for f in REGISTRY["families"] if f["family_id"] == "khadlaj_la_fede"
        )

    def test_individually_verified_la_fede_products_are_canonical(self):
        self.assertEqual({p["canonical_name"] for p in self.products}, set(EXPECTED))
        self.assertEqual(len(self.family["products"]), 36)

    def test_each_canonical_la_fede_product_has_official_detail_evidence(self):
        for name, expected in EXPECTED.items():
            product = next(p for p in self.products if p["canonical_name"] == name)
            self.assertEqual(product["identity_status"], "source_verified_name")
            self.assertEqual(product["source_product_url"], expected["url"])
            self.assertEqual(product["source_url"], expected["url"])

    def test_verified_variants_match_official_product_details(self):
        for name, expected in EXPECTED.items():
            product = next(p for p in self.products if p["canonical_name"] == name)
            variants = [
                v for v in CATALOG["variants"]
                if v["product_id"] == product["product_id"]
            ]
            self.assertEqual(len(variants), 1)
            self.assertEqual(variants[0]["size_ml"], expected["size_ml"])
            self.assertEqual(variants[0]["concentration"], expected["concentration"])

    def test_la_fede_products_are_not_duplicated_in_other_khadlaj_families(self):
        canonical_names = {p["canonical_name"].casefold() for p in self.products}
        for family in REGISTRY["families"]:
            if family["family_id"] == "khadlaj_la_fede":
                continue
            names = {p["canonical_name"].casefold() for p in family.get("products", [])}
            self.assertFalse(names & canonical_names)

    def test_product_and_variant_ids_are_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
