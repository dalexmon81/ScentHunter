"""Regression tests for individually verified Khadlaj La Fede identities.

The family registry and catalog include 42 individually reconciled La Fede identities. Only names with
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


EXPECTED_NAMES = {
    "La Fede Aura Crisp Flower", "La Fede Aura Kiss of Rose",
    "La Fede Aura Manga Splash", "La Fede Aura Pista Dessert",
    "La Fede Aura Vanilla Milk", "La Fede Bella Reve Dolce Flore",
    "La Fede Belle Reve Segrato Viola", "La Fede Celebrity Crush",
    "La Fede Celebrity Fame", "La Fede Celeste Aqua",
    "La Fede Celeste Fleur", "La Fede Celeste Joice",
    "La Fede Celeste Toffee", "La Fede Choco Brown",
    "La Fede Crystallia Imperio", "La Fede Crystallia Primaso",
    "La Fede Edge Intense", "La Fede Edge Original", "La Fede First Lady",
    "La Fede Intoxicate", "La Fede Intoxicate Blue Elixir",
    "La Fede Intoxicate Mystique", "La Fede Kingsman",
    "La Fede Lavish Blush", "La Fede Lavish Luna", "La Fede Lavish Rouge",
    "La Fede Magnum Extreme Blue", "La Fede Magnum Gold Edition",
    "La Fede Magnum Silver Edition", "La Fede Magnum Wild Green",
    "La Fede Miss Premiere", "La Fede Opera Noir L'Or",
    "La Fede Opera Rose L'Or", "La Fede Statesman",
    "La Fede Symbol of Love", "La Fede Symbol of Power",
    "La Fede White Forest Strawberry", "Uno Durable", "Uno Intimo",
    "Uno Lusso", "Uno Sensuale", "Code Viola Nectar",
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
        self.assertEqual({p["canonical_name"] for p in self.products}, EXPECTED_NAMES)
        self.assertEqual(len(self.family["products"]), 42)

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
