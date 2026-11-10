"""Four more Armaf EU official size details."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Infinity Silver": (105, "Eau de Parfum", "https://armaf.eu/products/infinity-silver-1"),
    "Ombre D'Or": (75, "Eau de Parfum", "https://cz.armaf.eu/en/products/ombre-dor"),
    "Island Bliss": (100, "Eau de Parfum", "https://cz.armaf.eu/en/products/delights-island-bliss"),
    "Yum Yum": (100, "Eau de Parfum", "https://cz.armaf.eu/en/products/delights-yum-yum"),
}


class ArmafFourMoreOfficialVariantsTests(unittest.TestCase):
    def test_four_existing_identities_have_official_eu_size_evidence(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        products = [p for p in CATALOG["products"] if p.get("brand") == "Armaf"]
        for name, (size, concentration, url) in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in products if p.get("canonical_name") == name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("concentration"), concentration)
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("source_product_url"), product.get("source_url"))
                self.assertEqual(product.get("source_evidence_url"), product.get("source_url"))
                self.assertEqual(product.get("source_size_evidence_url"), url)
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant.get("size_ml"), size)
                self.assertEqual(variant.get("concentration"), concentration)
                self.assertEqual(variant.get("source_size_evidence_url"), url)
                family_row = next(p for p in family["products"] if p.get("canonical_name") == name)
                self.assertEqual(family_row.get("formats_ml"), [size])
                self.assertEqual(family_row.get("concentration"), concentration)


if __name__ == "__main__":
    unittest.main()
