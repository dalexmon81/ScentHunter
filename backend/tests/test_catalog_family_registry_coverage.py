"""Cross-check canonical catalog identities against the family registry."""
import json
import unittest
import unicodedata
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


def normalized(value):
    value = unicodedata.normalize("NFD", str(value or ""))
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Mn")
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in value).split())


class CatalogFamilyRegistryCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.families = REGISTRY["families"]
        cls.families_by_id = {family["family_id"]: family for family in cls.families}

    def test_family_ids_are_unique(self):
        ids = [family["family_id"] for family in self.families]
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_catalog_identity_has_a_family_registry_entry(self):
        for product in self.products:
            with self.subTest(product=product["product_id"]):
                family = self.families_by_id.get(product.get("family_id"))
                self.assertIsNotNone(family, product.get("family_id"))
                names = {normalized(item["canonical_name"]) for item in family["products"]}
                self.assertIn(normalized(product["canonical_name"]), names)

    def test_canonical_brand_name_pairs_are_unique_after_accent_normalization(self):
        keys = [
            (normalized(product["brand"]), normalized(product["canonical_name"]))
            for product in self.products
        ]
        self.assertEqual(len(keys), len(set(keys)))

    def test_genesis_is_not_misclassified_as_liquid_brun_limited_edition(self):
        genesis = [p for p in self.products if p.get("family_id") == "french_avenue_genesis"]
        self.assertEqual(len(genesis), 11)
        liquid_brun = self.families_by_id["french_avenue_liquid_brun_limited_edition"]
        self.assertEqual(
            {p["canonical_name"] for p in liquid_brun["products"]},
            {"Liquid Brun Limited Edition"},
        )

    def test_asad_family_is_not_a_bucket_for_unrelated_lattta_products(self):
        asad = self.families_by_id["lattafa_asad"]
        self.assertEqual(
            {p["canonical_name"] for p in asad["products"]},
            {"Asad", "Asad Zanzibar", "Asad Bourbon", "Asad Elixir"},
        )

    def test_accent_only_duplicate_is_one_identity_with_three_sizes(self):
        products = [
            p for p in self.products
            if p.get("brand") == "Giorgio Armani"
            and normalized(p.get("canonical_name")) == normalized("Acqua di Gio Profondo")
        ]
        self.assertEqual(len(products), 1)
        product = products[0]
        self.assertIn("Acqua di Giò Profondo", product["aliases"])
        self.assertEqual(product["formats_ml"], [75, 100, 125])
        sizes = {
            variant["size_ml"]
            for variant in CATALOG["variants"]
            if variant["product_id"] == product["product_id"]
        }
        self.assertEqual(sizes, {75, 100, 125})


if __name__ == "__main__":
    unittest.main()
