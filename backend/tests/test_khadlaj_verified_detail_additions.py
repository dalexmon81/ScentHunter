"""Official detail-page regression tests for two Khadlaj launches."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))


class KhadlajVerifiedDetailAdditionsTests(unittest.TestCase):
    def test_products_and_variants_match_official_detail_pages(self):
        expected = {
            "Muse": ("https://khadlaj-perfumes.com/products/khadlaj-muse-100-ml-eau-de-parfum-spray-for-women", "Eau de Parfum", 100),
            "Onyx Galaxy": ("https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/khadlaj-onyx-galaxy-100-ml-eau-de-parfum-for-men", "Eau de Parfum", 100),
        }
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand") == "Khadlaj"}
        for name, (url, concentration, size) in expected.items():
            with self.subTest(product=name):
                p = products[name]
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["source_url"], url)
                self.assertEqual(p["concentration"], concentration)
                variants = [v for v in CATALOG["variants"] if v["product_id"] == p["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], size)
                self.assertEqual(variants[0]["concentration"], concentration)
                self.assertEqual(variants[0]["source_evidence_url"], url)

    def test_family_registry_contains_both_products(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "khadlaj_catalog")
        names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue({"Muse", "Onyx Galaxy"}.issubset(names))


if __name__ == "__main__":
    unittest.main()
