"""Official Paris Corner Europe size/concentration reconciliation for eleven identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Bayn Al Asrar": (80, "https://de.pariscornereurope.com/en/products/paris-corner-bayn-al-asrar-edp-w-80-ml"),
    "December Rose": (85, "https://de.pariscornereurope.com/en/products/paris-corner-december-rose-edp-u-85-ml"),
    "December Vanilla": (85, "https://de.pariscornereurope.com/en/products/paris-corner-december-vanilla-edp-u-85-ml"),
    "Khair Pistachio": (100, "https://de.pariscornereurope.com/en/products/khair-pistachio"),
    "Khair Confection": (100, "https://de.pariscornereurope.com/en/products/khair-confection"),
    "Khair Fusion": (100, "https://de.pariscornereurope.com/en/products/khair-fusion"),
    "Khair Felicity": (100, "https://de.pariscornereurope.com/en/products/khair-felicity"),
    "Mawj Appletini": (100, "https://de.pariscornereurope.com/en/products/mawj-appletini"),
    "Mawj Moscow Mule": (100, "https://de.pariscornereurope.com/en/products/paris-corner-mawj-moscow-mule-edp-u-100-ml"),
    "Mawj Cognac Blaze": (100, "https://de.pariscornereurope.com/products/mawj-cognac-blaze"),
    "Minya Coco Lush": (100, "https://de.pariscornereurope.com/en/products/minya-coco-lush"),
}


class ParisCornerAdditionalOfficialVariantsTests(unittest.TestCase):
    def test_eleven_existing_identities_have_official_eu_variant_evidence(self):
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
                self.assertEqual(product.get("concentration"), "Eau de Parfum")
                self.assertEqual(product.get("formats_ml"), [size])

                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant.get("size_ml"), size)
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("source_url"), product.get("source_url"))
                self.assertEqual(variant.get("source_evidence_url"), product.get("source_url"))
                self.assertEqual(variant.get("source_product_url"), url)

                rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), [size])
                self.assertEqual(rows[0].get("concentration"), "Eau de Parfum")

    def test_no_product_or_variant_ids_are_duplicated_and_no_variant_is_orphaned(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        known = set(product_ids)
        self.assertTrue(all(v["product_id"] in known for v in CATALOG["variants"]))


if __name__ == "__main__":
    unittest.main()
