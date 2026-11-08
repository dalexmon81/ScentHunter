"""Regression coverage for Paris Corner Europe individual product pages and EDP variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Date Caramel": ("SH-PARIS-CORNER-807b8de9", "https://de.pariscornereurope.com/en/products/date-caramel", "Eau de Parfum"),
    "Indomitable": ("SH-PARIS-CORNER-INDOMITABLE", "https://de.pariscornereurope.com/en/products/indomitable", "Eau de Parfum"),
    "Mawj Moscow Mule": ("SH-PARIS-CORNER-MAWJ-MOSCOW-MULE", "https://de.pariscornereurope.com/en/products/paris-corner-mawj-moscow-mule-edp-u-100-ml", "Eau de Parfum"),
    "Perseviron Fig Hug": ("SH-PARIS-CORNER-18f3d5a4", "https://de.pariscornereurope.com/en/products/pc-fig-hug-perseviron-edp-u-100-ml", "Eau de Parfum"),
    "Tiramisu Speculoos": ("SH-PARIS-CORNER-TIRAMISU-SPECULOOS", "https://www.pariscornerperfumes.com/products/tiramisu-speculoos-100ml", None),
}


class ParisCornerEuropeOfficialVariantTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Paris Corner"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "paris_corner_catalog"
        )

    def test_official_pages_and_edp_variants(self):
        for name, (product_id, url, concentration) in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product["source_evidence_url"], url)
                self.assertEqual(product["formats_ml"], [100])
                if concentration is None:
                    self.assertNotIn("concentration", product)
                else:
                    self.assertEqual(product["concentration"], concentration)
                matches = [
                    v for v in self.variants
                    if v.get("product_id") == product_id
                    and v.get("size_ml") == 100
                    and v.get("concentration") == concentration
                ]
                self.assertEqual(len(matches), 1)

    def test_fig_hug_alias_resolves_to_existing_perseviron_identity(self):
        product = self.products["Perseviron Fig Hug"]
        self.assertIn("Fig Hug", product["aliases"])
        self.assertIn("Paris Corner Fig Hug", product["aliases"])

    def test_tiramisu_concentration_is_not_inferred(self):
        product = self.products["Tiramisu Speculoos"]
        self.assertEqual(product["formats_ml"], [100])
        self.assertNotIn("concentration", product)

    def test_family_registry_formats_are_aligned(self):
        for name in EXPECTED:
            with self.subTest(product=name):
                registry_product = next(
                    p for p in self.family["products"]
                    if p["canonical_name"] == name
                )
                self.assertIn(100, registry_product.get("formats_ml", []))

    def test_variant_ids_are_unique_and_parent_products_exist(self):
        ids = [v["variant_id"] for v in self.variants]
        product_ids = {p["product_id"] for p in CATALOG["products"]}
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v["product_id"] in product_ids for v in self.variants))


if __name__ == "__main__":
    unittest.main()
