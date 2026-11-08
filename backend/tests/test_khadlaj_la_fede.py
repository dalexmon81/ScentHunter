"""Regression tests for Khadlaj La Fede collection reconciliation."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class KhadlajLaFedeTests(unittest.TestCase):
    def setUp(self):
        self.products = [
            p for p in CATALOG["products"]
            if p.get("brand") == "Khadlaj" and p.get("family_id") == "khadlaj_la_fede"
        ]
        self.family = next(
            f for f in REGISTRY["families"] if f["family_id"] == "khadlaj_la_fede"
        )

    def test_official_la_fede_parent_collection_and_new_launch_are_reconciled(self):
        self.assertEqual(len(self.products), 36)
        names = {p["canonical_name"] for p in self.products}
        self.assertIn("La Fede Intoxicate Mystique", names)
        self.assertIn("La Fede Celebrity Crush", names)
        self.assertIn("La Fede Celebrity Fame", names)

    def test_family_registry_has_exact_product_parity(self):
        catalog_names = {p["canonical_name"].casefold() for p in self.products}
        registry_names = {p["canonical_name"].casefold() for p in self.family["products"]}
        self.assertEqual(catalog_names, registry_names)

    def test_la_fede_products_are_removed_from_other_khadlaj_families(self):
        for family in REGISTRY["families"]:
            if family["family_id"] == "khadlaj_la_fede":
                continue
            names = {p["canonical_name"].casefold() for p in family.get("products", [])}
            self.assertFalse(names & {p["canonical_name"].casefold() for p in self.products})

    def test_celebrity_crush_and_fame_have_verified_100ml_edp_variants(self):
        for name in ("La Fede Celebrity Crush", "La Fede Celebrity Fame"):
            product = next(p for p in self.products if p["canonical_name"] == name)
            variant = next(v for v in CATALOG["variants"] if v["product_id"] == product["product_id"])
            self.assertEqual(variant["size_ml"], 100)
            self.assertEqual(variant["concentration"], "Eau de Parfum")

    def test_intoxicate_mystique_is_verified_100ml_extrait(self):
        product = next(p for p in self.products if p["canonical_name"] == "La Fede Intoxicate Mystique")
        variant = next(v for v in CATALOG["variants"] if v["product_id"] == product["product_id"])
        self.assertEqual(variant["size_ml"], 100)
        self.assertEqual(variant["concentration"], "Extrait de Parfum")
        self.assertEqual(product["source_product_url"], "https://khadlaj-perfumes.com/collections/new-launch-la-fede-eau-de-parfum-collection-by-khadlaj-perfumes/products/la-fede-intoxicate-blue-elixir-100-ml-eau-de-parfume-spray-for-men-copy")

    def test_product_ids_and_variant_ids_are_unique(self):
        ids = [p["product_id"] for p in self.products]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
