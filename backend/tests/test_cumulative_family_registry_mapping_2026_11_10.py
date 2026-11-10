"""Ensure every canonical catalog product maps to exactly one family row."""
import json
import re
import unicodedata
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

def normalize(value):
    value = unicodedata.normalize("NFD", value or "")
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()

class CumulativeFamilyRegistryMappingTests(unittest.TestCase):
    def test_registry_has_no_normalized_duplicate_canonical_names(self):
        for family in REGISTRY["families"]:
            keys = [normalize(row.get("canonical_name")) for row in family.get("products", [])]
            with self.subTest(family=family.get("family_id")):
                self.assertEqual(len(keys), len(set(keys)))

    def test_each_catalog_product_maps_to_exactly_one_registry_row(self):
        families = {family["family_id"]: family for family in REGISTRY["families"]}
        for product in CATALOG["products"]:
            family = families.get(product.get("family_id"))
            self.assertIsNotNone(family, product.get("product_id"))
            name = normalize(product.get("canonical_name"))
            matches = [row for row in family.get("products", [])
                       if normalize(row.get("canonical_name")) == name
                       or any(normalize(alias) == name for alias in row.get("aliases", []))]
            with self.subTest(product=product.get("product_id")):
                self.assertEqual(len(matches), 1)

    def test_confidential_100ml_is_not_an_alias_of_confidential(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "paris_corner_catalog")
        confidential = next(p for p in family["products"] if p["canonical_name"] == "Confidential")
        confidential_100 = next(p for p in family["products"] if p["canonical_name"] == "Confidential 100ML")
        self.assertNotIn("Confidential 100ML", confidential.get("aliases", []))
        self.assertEqual(confidential_100.get("formats_ml"), [100])

if __name__ == "__main__":
    unittest.main()
