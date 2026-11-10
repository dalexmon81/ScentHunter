"""Cross-PR catalog uniqueness guards for the consolidated seed."""
import json
import re
import unicodedata
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


def normalized(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]", "", value.casefold())


class CrossPRCatalogUniquenessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG.get("products", [])
        cls.variants = CATALOG.get("variants", [])

    def test_product_ids_are_unique(self):
        ids = [row.get("product_id") for row in self.products]
        self.assertTrue(all(ids), "Every product must have a product_id")
        self.assertEqual(len(ids), len(set(ids)), "Duplicate product_id detected")

    def test_normalized_brand_and_canonical_identity_are_unique(self):
        identities = {}
        for row in self.products:
            brand = row.get("brand_name") or row.get("brand")
            name = row.get("canonical_name") or row.get("name")
            key = (normalized(brand), normalized(name))
            self.assertTrue(all(key), f"Missing brand or canonical name: {row!r}")
            identities.setdefault(key, []).append(row.get("product_id"))
        duplicates = {
            key: product_ids
            for key, product_ids in identities.items()
            if len(product_ids) > 1
        }
        self.assertEqual(
            duplicates,
            {},
            "The same fragrance identity appears more than once after "
            "case, punctuation and diacritic normalization.",
        )

    def test_variant_ids_are_unique(self):
        ids = [row.get("variant_id") for row in self.variants]
        self.assertTrue(all(ids), "Every variant must have a variant_id")
        self.assertEqual(len(ids), len(set(ids)), "Duplicate variant_id detected")

    def test_product_size_concentration_variant_tuples_are_unique(self):
        tuples = {}
        for row in self.variants:
            key = (
                row.get("product_id"),
                row.get("size_ml"),
                normalized(row.get("concentration")),
            )
            tuples.setdefault(key, []).append(row.get("variant_id"))
        duplicates = {
            key: variant_ids
            for key, variant_ids in tuples.items()
            if len(variant_ids) > 1
        }
        self.assertEqual(
            duplicates,
            {},
            "Duplicate product/size/concentration variant tuple detected, "
            "even if the variant IDs differ.",
        )

    def test_every_variant_references_an_existing_product(self):
        product_ids = {row.get("product_id") for row in self.products}
        missing = [
            row.get("variant_id")
            for row in self.variants
            if row.get("product_id") not in product_ids
        ]
        self.assertEqual(missing, [], "Orphan variants reference missing products")

    def test_family_registry_canonical_rows_are_exactly_unique(self):
        for family in REGISTRY.get("families", []):
            names = [
                row.get("canonical_name")
                for row in family.get("products", [])
            ]
            self.assertTrue(
                all(names),
                f"Family {family.get('family_id')} has an unnamed product row",
            )
            self.assertEqual(
                len(names),
                len(set(names)),
                f"Family {family.get('family_id')} repeats an exact canonical row",
            )


if __name__ == "__main__":
    unittest.main()
