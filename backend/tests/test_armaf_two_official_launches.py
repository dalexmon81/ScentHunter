"""Two new Armaf identities from official European product pages."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Dunescape Dubai": ("SH-ARMAF-DUNESCAPE-DUBAI", "https://armaf.eu/products/dunescape", 100, "Extrait de Parfum", "SHV-SH-ARMAF-DUNESCAPE-DUBAI-100-000"),
    "Check Mate White Knight": ("SH-ARMAF-CHECK-MATE-WHITE-KNIGHT", "https://cz.armaf.eu/en/products/check-mate-white-knight", 100, "Eau de Parfum", "SHV-SH-ARMAF-CHECK-MATE-WHITE-KNIGHT-100-000"),
}


class ArmafTwoOfficialLaunchesTests(unittest.TestCase):
    def test_new_products_have_official_sources_and_explicit_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        for name, (product_id, url, size, concentration, variant_id) in EXPECTED.items():
            with self.subTest(product=name):
                products = [p for p in CATALOG["products"] if p.get("brand_name") == "Armaf" and p.get("canonical_name") == name]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product.get("product_id"), product_id)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("concentration"), concentration)
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), variant_id)
                self.assertEqual(variants[0].get("size_ml"), size)
                self.assertEqual(variants[0].get("concentration"), concentration)
                self.assertEqual(variants[0].get("source_evidence_url"), url)
                family_rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0].get("formats_ml"), [size])


if __name__ == "__main__":
    unittest.main()
