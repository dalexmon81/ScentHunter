"""Official Paris Corner Europe detail evidence for four more catalog identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Bayn Al Asrar": ("https://de.pariscornereurope.com/en/products/paris-corner-bayn-al-asrar-edp-w-80-ml", 80),
    "Caramel Bash": ("https://de.pariscornereurope.com/en/products/paris-corner-caramel-bash-edp-u-100-ml", 100),
    "December Rose": ("https://de.pariscornereurope.com/en/products/paris-corner-december-rose-edp-u-85-ml", 85),
    "Cosmic Giardino": ("https://de.pariscornereurope.com/en/products/paris-corner-cosmic-giardino-edp-u-100-ml", 100),
}


class ParisCornerFourOfficialDetailTests(unittest.TestCase):
    def test_existing_identities_have_official_evidence_and_exact_size_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "paris_corner_catalog")
        for name, (url, size) in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in CATALOG["products"] if p.get("brand_name") == "Paris Corner" and p.get("canonical_name") == name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertEqual(product.get("source_url"), url)
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [size])
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0].get("variant_id"), f"SHV-{product['product_id']}-{size}-EDP")
                self.assertEqual(variants[0].get("size_ml"), size)
                self.assertEqual(variants[0].get("concentration"), "Eau de Parfum")
                self.assertEqual(variants[0].get("source_evidence_url"), url)
                family_rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0].get("formats_ml"), [size])
                self.assertEqual(family_rows[0].get("concentration"), "Eau de Parfum")


if __name__ == "__main__":
    unittest.main()
