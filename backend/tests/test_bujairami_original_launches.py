"""Individual official-page evidence for Bujairami's four original EU launches."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Gold Coast Shiraz": ("SH-BUJAIRAMI-370cb2f2", "https://bujairami.eu/product/gold-coast-shiraz/", "Eau de Parfum"),
    "G’Day": ("SH-BUJAIRAMI-ee29a117", "https://bujairami.eu/product/gday/", "Extrait de Parfum"),
    "Midnight in Melbourne": ("SH-BUJAIRAMI-6110beb5", "https://bujairami.eu/product/midnight-in-melbourne/", "Eau de Parfum"),
    "Sunrise in Sydney": ("SH-BUJAIRAMI-e55dcd47", "https://bujairami.eu/product/sunrise-in-sydney/", "Eau de Parfum"),
}


class BujairamiOriginalLaunchTests(unittest.TestCase):
    def test_official_detail_identity_and_provenance(self):
        for name, (product_id, url, _) in EXPECTED.items():
            with self.subTest(name=name):
                matches = [
                    p for p in CATALOG["products"]
                    if p.get("brand") == "Bujairami" and p.get("canonical_name") == name
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["product_id"], product_id)
                self.assertEqual(matches[0]["identity_status"], "source_verified_name")
                self.assertEqual(matches[0]["source_url"], url)
                self.assertEqual(matches[0]["source_product_url"], url)

    def test_100ml_variants_and_concentrations(self):
        for name, (product_id, _, concentration) in EXPECTED.items():
            with self.subTest(name=name):
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == product_id]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], 100)
                self.assertEqual(variants[0]["concentration"], concentration)

    def test_family_registry_has_matching_100ml_formats(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "bujairami_catalog")
        for name in EXPECTED:
            with self.subTest(name=name):
                product = next(p for p in family["products"] if p["canonical_name"] == name)
                self.assertEqual(product["formats_ml"], [100])


if __name__ == "__main__":
    unittest.main()
