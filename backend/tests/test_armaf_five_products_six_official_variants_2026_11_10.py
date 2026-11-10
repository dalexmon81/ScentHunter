"""Official Armaf EU size evidence for five existing canonical products."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Club de Nuit Intense Man Pure Parfum": [
        (150, "Parfum", "https://armaf.eu/products/armaf-club-de-nuit-intense-man-pure-perfume"),
        (200, "Parfum", "https://armaf.eu/products/armaf-club-de-nuit-intense-man-pure-perfume"),
    ],
    "Club de Nuit Bling": [
        (75, "Eau de Parfum", "https://armaf.eu/products/club-de-nuit-bling"),
    ],
    "Club de Nuit Lionheart Man": [
        (100, "Eau de Parfum", "https://cz.armaf.eu/en/products/club-de-nuit-lion-heart-man"),
    ],
    "Club de Nuit Lionheart Woman": [
        (100, "Eau de Parfum", "https://cz.armaf.eu/en/products/club-de-nuit-lion-heart-woman"),
    ],
    "Club de Nuit Maleka": [
        (105, "Eau de Parfum", "https://fr.armaf.eu/products/club-de-nuit-maleka"),
    ],
}


class ArmafFiveProductsSixOfficialVariantsTests(unittest.TestCase):
    def test_existing_identities_have_official_eu_size_evidence(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "armaf_catalog")
        products = [p for p in CATALOG["products"] if p.get("brand") == "Armaf"]
        for name, expected_variants in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in products if p.get("canonical_name") == name)
                self.assertEqual(product.get("identity_status"), "source_verified_name")
                self.assertTrue((product.get("source_url") or "").startswith("https://armaf.com/"))
                self.assertEqual(product.get("source_evidence_url"), product.get("source_url"))
                self.assertEqual(product.get("source_product_url"), expected_variants[0][2])
                self.assertEqual(product.get("formats_ml"), sorted({size for size, _, _ in expected_variants}))
                rows = [v for v in CATALOG["variants"] if v.get("product_id") == product["product_id"]]
                for size, concentration, url in expected_variants:
                    variant = next(v for v in rows if v.get("size_ml") == size and v.get("concentration") == concentration)
                    self.assertEqual(variant.get("source_url"), product.get("source_url"))
                    self.assertEqual(variant.get("source_evidence_url"), product.get("source_url"))
                    self.assertEqual(variant.get("source_product_url"), url)
                family_row = next(p for p in family["products"] if p.get("canonical_name") == name)
                self.assertEqual(family_row.get("formats_ml"), sorted({size for size, _, _ in expected_variants}))


if __name__ == "__main__":
    unittest.main()
