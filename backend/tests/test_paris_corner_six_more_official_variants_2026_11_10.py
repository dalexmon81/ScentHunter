"""Six additional Paris Corner Europe official product-page variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Cosmopolitan Newyork": (100, "https://de.pariscornereurope.com/en/products/cosmopolitan-newyork"),
    "Eternal Coffee": (85, "https://de.pariscornereurope.com/en/products/eternal-coffee"),
    "Eternal Meadows": (85, "https://de.pariscornereurope.com/en/products/eternal-meadows"),
    "Eternal Musk": (85, "https://de.pariscornereurope.com/en/products/eternal-musk"),
    "Khair": (100, "https://de.pariscornereurope.com/en/products/khair"),
    "Manaal": (100, "https://de.pariscornereurope.com/en/products/paris-corner-manaal-edp-u-100-ml"),
}


class ParisCornerSixMoreOfficialVariantsTests(unittest.TestCase):
    def test_six_existing_identities_have_official_eu_variant_evidence(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "paris_corner_catalog")
        products = [p for p in CATALOG["products"] if p.get("brand") == "Paris Corner"]
        for name, (size, url) in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in products if p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertTrue((product.get("source_url") or "").startswith("https://www.pariscornerperfumes.com/"))
                self.assertEqual(product.get("source_evidence_url"), product.get("source_url"))
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("formats_ml"), [size])
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant.get("size_ml"), size)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("source_product_url"), url)
                row = next(p for p in family["products"] if p.get("canonical_name") == name)
                self.assertEqual(row.get("formats_ml"), [size])
                self.assertEqual(row.get("concentration"), "Eau de Parfum")


if __name__ == "__main__":
    unittest.main()
