"""Family registry format synchronization for fully verified Maison Alhambra products."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Alpine Homme Sport": ("SH-MAISON-ALHAMBRA-0840cbf0", 100),
    "Aura D'Eclat": ("SH-MAISON-ALHAMBRA-7c1ece5a", 100),
    "Avant Ruby": ("SH-MAISON-ALHAMBRA-f80b4af7", 100),
    "Avant Silk": ("SH-MAISON-ALHAMBRA-1bc577a6", 100),
    "Baroque Satin Oud": ("SH-MAISON-ALHAMBRA-b9e265b9", 100),
    "Berlinetta": ("SH-MAISON-ALHAMBRA-0da920d5", 100),
    "Black Origami": ("SH-MAISON-ALHAMBRA-e3d1182c", 100),
}


class MaisonAlhambraRegistryFormatSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.families = {f["family_id"]: f for f in REGISTRY["families"]}

    def test_family_registry_formats_match_fully_verified_catalog_products(self):
        for name, (product_id, expected_size) in EXPECTED.items():
            with self.subTest(product=name):
                products = [p for p in self.products if p.get("product_id") == product_id]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("brand_name", product.get("brand")), "Maison Alhambra")
                self.assertEqual(product.get("canonical_name"), name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("formats_ml"), [expected_size])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                family = self.families[product["family_id"]]
                rows = [r for r in family["products"] if r.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [expected_size])
                variants = [
                    v for v in self.variants
                    if v.get("product_id") == product_id
                ]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("size_ml"), expected_size)

    def test_no_catalog_or_registry_product_ids_are_changed(self):
        ids = [p.get("product_id") for p in self.products]
        self.assertEqual(len(ids), len(set(ids)))
        variants = [v.get("variant_id") for v in self.variants]
        self.assertEqual(len(variants), len(set(variants)))
        known = set(ids)
        self.assertTrue(all(v.get("product_id") in known for v in self.variants))


if __name__ == "__main__":
    unittest.main()
