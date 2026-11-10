"""Regression checks for canonical family-registry identity uniqueness."""
import json
import re
import unicodedata
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


def normalized_name(value):
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


class FamilyRegistryIdentityTests(unittest.TestCase):
    def test_no_normalized_duplicate_names_remain_within_a_family(self):
        for family in REGISTRY["families"]:
            keys = [normalized_name(p.get("canonical_name")) for p in family.get("products", [])]
            with self.subTest(family=family.get("family_id")):
                self.assertEqual(len(keys), len(set(keys)))

    def test_each_catalog_product_maps_to_exactly_one_registry_identity(self):
        families = {family["family_id"]: family for family in REGISTRY["families"]}
        for product in CATALOG["products"]:
            family = families.get(product.get("family_id"))
            if family is None:
                continue
            key = normalized_name(product.get("canonical_name"))
            matches = [row for row in family.get("products", []) if normalized_name(row.get("canonical_name")) == key]
            with self.subTest(product_id=product.get("product_id")):
                self.assertEqual(len(matches), 1)

    def test_merged_spellings_are_preserved_as_aliases(self):
        expected = {
            ("paris_corner_catalog", "Deux II Expressions North Stag"): {"Deux II Expressions, North Stag", "Paris Corner Deux II Expressions, North Stag"},
            ("arabiyat_prestige_catalog", "Noirè"): {"Noire", "Arabiyat Prestige Noire"},
            ("lattafa_catalog", "Ajwad Pink to Pink"): {"Ajwad Pink To Pink", "Lattafa Ajwad Pink To Pink"},
        }
        families = {family["family_id"]: family for family in REGISTRY["families"]}
        for (family_id, canonical), aliases in expected.items():
            family = families[family_id]
            row = next(p for p in family["products"] if p.get("canonical_name") == canonical)
            with self.subTest(family=family_id, canonical=canonical):
                self.assertTrue(aliases.issubset(set(row.get("aliases", []))))


if __name__ == "__main__":
    unittest.main()
