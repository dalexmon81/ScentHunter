"""Paris Corner Europe official product-page evidence for eleven existing identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Coconut Lagoon": ("https://de.pariscornereurope.com/en/products/coconut-lagoon", 100),
    "Eshal Vanilla": ("https://de.pariscornereurope.com/en/products/paris-corner-eshal-vanilla-edp-u-100-ml", 100),
    "Ibisco Nirvana": ("https://de.pariscornereurope.com/en/products/ibisco-nirvana", 65),
    "Hurriya": ("https://de.pariscornereurope.com/en/products/paris-corner-hurriya-edp-u-100-ml", 100),
    "Miel Vanille": ("https://de.pariscornereurope.com/en/products/pc-miel-vanille-edp-u-100-ml", 100),
    "Qissa": ("https://de.pariscornereurope.com/en/products/qissa", 100),
    "Fayora": ("https://de.pariscornereurope.com/en/products/pc-fayora-edp-w-100-ml", 100),
    "Fayora Oshino": ("https://de.pariscornereurope.com/en/products/pc-fayora-oshino-edp-w-100-ml", 100),
    "Qissa Gala": ("https://de.pariscornereurope.com/en/products/pc-qissa-gala-edp-w-100-ml", 100),
    "Qissa Delicious": ("https://de.pariscornereurope.com/en/products/qissa-delicious", 100),
    "Qissa Pink": ("https://de.pariscornereurope.com/en/products/qissa-pink", 100),
}


class ParisCornerElevenOfficialDetailTests(unittest.TestCase):
    def test_existing_identities_have_official_detail_evidence_and_variants(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "paris_corner_catalog")
        products = [p for p in CATALOG["products"] if p.get("brand_name") == "Paris Corner"]
        for name, (url, size) in EXPECTED.items():
            with self.subTest(product=name):
                matches = [p for p in products if p.get("canonical_name") == name]
                self.assertEqual(len(matches), 1)
                product = matches[0]
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertTrue((product.get("source_url") or "").startswith("https://www.pariscornerperfumes.com/"))
                self.assertEqual(product.get("source_product_url"), url)
                self.assertEqual(product.get("source_evidence_url"), url)
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [size])

                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertTrue(variant.get("variant_id"))
                self.assertEqual(variant.get("size_ml"), size)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("source_product_url"), url)
                self.assertEqual(variant.get("source_evidence_url"), url)

                family_rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(family_rows), 1)
                self.assertEqual(family_rows[0].get("formats_ml"), [size])
                self.assertEqual(family_rows[0].get("concentration"), "Eau de Parfum")


if __name__ == "__main__":
    unittest.main()
