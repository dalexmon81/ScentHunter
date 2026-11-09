"""Regression checks for the reconciled official Armaf identity set."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Odyssey Pink Pop": ("SH-ARMAF-ODYSSEY-PINK-POP", "https://armaf.com/products/odyssey-pink-pop-edp", None, "Eau de Parfum"),
    "Odyssey French Kiss": ("SH-ARMAF-ODYSSEY-FRENCH-KISS", "https://armaf.com/products/odyssey-french-kiss", [60], "Eau de Parfum"),
    "Odyssey Soda Pop": ("SH-ARMAF-ODYSSEY-SODA-POP", "https://www.armaf.ae/products/odyssey-soda-pop", [100], "Eau de Parfum"),
    "Dunescape Dubai": ("SH-ARMAF-DUNESCAPE-DUBAI", "https://armaf.eu/products/dunescape", [100], "Extrait de Parfum"),
    "Check Mate White Knight": ("SH-ARMAF-CHECK-MATE-WHITE-KNIGHT", "https://cz.armaf.eu/en/products/check-mate-white-knight", [100], "Eau de Parfum"),
    "Odyssey Tyrant Special Edition": ("SH-ARMAF-5111fab1", "https://cz.armaf.eu/en/products/odyssey-tyrant-special-edition", [60, 100], "Eau de Parfum"),
    "Odyssey Eau de Montagne Mountain Edition": ("SH-ARMAF-332c2520", "https://cz.armaf.eu/en/products/odyssey-eau-de-montagne-mountain-edition", [100], "Eau de Parfum"),
    "Dubai Delicacy Kunafa Chocolate": ("SH-ARMAF-b428c109", "https://cz.armaf.eu/products/dubai-delicacy", [70], "Eau de Parfum"),
}

class ArmafReconciledOfficialIdentityTests(unittest.TestCase):
    def test_canonical_identities_sources_and_variants(self):
        products = {p["canonical_name"]: p for p in CATALOG["products"] if p.get("brand_name") == "Armaf"}
        for name, (product_id, url, sizes, concentration) in EXPECTED.items():
            with self.subTest(product=name):
                self.assertIn(name, products)
                product = products[name]
                self.assertEqual(product["product_id"], product_id)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], url)
                self.assertEqual(product.get("concentration"), concentration)
                if sizes is not None:
                    self.assertEqual(product.get("formats_ml"), sizes)
                    variants = [v for v in CATALOG["variants"] if v["product_id"] == product_id]
                    self.assertEqual(sorted(v["size_ml"] for v in variants), sorted(sizes))
                    self.assertTrue(all(v.get("concentration") == concentration for v in variants))
                else:
                    self.assertFalse(any(v["product_id"] == product_id for v in CATALOG["variants"]))

    def test_check_mate_and_french_kiss_have_one_canonical_record(self):
        for name in ("Check Mate White Knight", "Odyssey French Kiss"):
            rows = [p for p in CATALOG["products"] if p.get("brand_name") == "Armaf" and p.get("canonical_name") == name]
            self.assertEqual(len(rows), 1)
        french = next(p for p in CATALOG["products"] if p.get("product_id") == EXPECTED["Odyssey French Kiss"][0])
        self.assertIn("https://cz.armaf.eu/products/odyssey-french-kiss", french["source_evidence_url"])
        check = next(p for p in CATALOG["products"] if p.get("product_id") == EXPECTED["Check Mate White Knight"][0])
        self.assertIn("Check Mate White Knight", check["aliases"])
        self.assertIn("Check Mate White - Knight", check["aliases"])

    def test_family_registry_has_one_entry_per_new_identity(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "armaf_catalog")
        names = [p["canonical_name"] for p in family["products"]]
        for name in EXPECTED:
            self.assertEqual(names.count(name), 1, name)

    def test_all_product_and_variant_ids_are_unique_and_variants_have_parents(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        product_id_set = set(product_ids)
        self.assertTrue(all(v["product_id"] in product_id_set for v in CATALOG["variants"]))

if __name__ == "__main__":
    unittest.main()
