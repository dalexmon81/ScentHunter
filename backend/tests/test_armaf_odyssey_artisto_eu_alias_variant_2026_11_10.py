"""Odyssey Artisto official EU edition name and 100 ml EDP variant."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

class ArmafOdysseyArtistoEuAliasVariantTests(unittest.TestCase):
    def test_eu_edition_matches_existing_artisto_note_pyramid_and_size(self):
        product = next(p for p in CATALOG["products"] if p.get("brand") == "Armaf" and p.get("canonical_name") == "Odyssey Artisto")
        alias = "Odyssey Artisto The Red Edition"
        url = "https://cz.armaf.eu/en/products/odyssey-artisto-the-red-edition"
        self.assertIn(alias, product.get("aliases", []))
        self.assertEqual(product.get("formats_ml"), [100])
        self.assertEqual(product.get("concentration"), "Eau de Parfum")
        self.assertEqual(product.get("source_product_url"), product.get("source_url"))
        self.assertEqual(product.get("source_size_evidence_url"), url)
        variant = next(v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"])
        self.assertEqual(variant.get("size_ml"), 100)
        self.assertEqual(variant.get("concentration"), "Eau de Parfum")
        self.assertIn(alias, variant.get("aliases", []))
        self.assertEqual(variant.get("source_size_evidence_url"), url)
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        row = next(p for p in family["products"] if p.get("canonical_name") == "Odyssey Artisto")
        self.assertIn(alias, row.get("aliases", []))
        self.assertEqual(row.get("formats_ml"), [100])

if __name__ == "__main__":
    unittest.main()
