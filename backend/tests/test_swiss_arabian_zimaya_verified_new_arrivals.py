"""Verified Swiss Arabian and Zimaya first-party additions and variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Swiss Arabian": {
        "Shaghaf Nectar Blush": ("https://swissarabian.com/products/shaghaf-nectar-blush", 75, "Eau de Parfum", "https://us.swissarabian.com/"),
        "Patchouli 01": ("https://swissarabian.com/products/patchouli-01", 50, "Extrait de Parfum", "https://us.swissarabian.com/"),
        "Shaghaf Oud Marine": ("https://swissarabian.com/products/shaghaf-oud-marine", 75, "Eau de Parfum", "https://us.swissarabian.com/"),
        "Echoes of St. Moritz": ("https://swissarabian.com/products/echoes-of-st-moritz", 100, "Extrait de Parfum", "https://us.swissarabian.com/"),
    },
    "Zimaya": {
        "Siada Regal": ("https://us.zimayaperfumes.com/products/siada-regal-perfume", 100, "Eau de Parfum", "https://us.zimayaperfumes.com/products/siada-regal-perfume"),
        "Siada Nova": ("https://us.zimayaperfumes.com/products/siada-nova-perfume", 100, "Eau de Parfum", "https://us.zimayaperfumes.com/products/siada-nova-perfume"),
        "Nojoum": ("https://us.zimayaperfumes.com/products/nojoum-perfume-oil", 20, "Concentrated Perfume Oil", "https://us.zimayaperfumes.com/products/nojoum-perfume-oil"),
    },
}


class VerifiedSwissArabianZimayaTests(unittest.TestCase):
    def test_verified_identities_and_explicit_variants(self):
        products = {
            (p.get("brand_name"), p.get("canonical_name")): p
            for p in CATALOG["products"]
        }
        variants = CATALOG["variants"]
        for brand, rows in EXPECTED.items():
            for name, (url, size, concentration, evidence_url) in rows.items():
                with self.subTest(brand=brand, name=name):
                    product = products[(brand, name)]
                    self.assertEqual(product["identity_status"], "source_verified_name")
                    self.assertEqual(product["source_url"], url)
                    self.assertEqual(product["source_product_url"], url)
                    self.assertEqual(product["concentration"], concentration)
                    self.assertIn(size, product["formats_ml"])
                    matching = [
                        v for v in variants
                        if v.get("product_id") == product["product_id"]
                        and v.get("size_ml") == size
                    ]
                    self.assertEqual(len(matching), 1)
                    self.assertEqual(matching[0]["concentration"], concentration)
                    self.assertEqual(matching[0]["source_evidence_url"], evidence_url)
                    self.assertNotIn("price", matching[0])
                    self.assertNotIn("stock", matching[0])

    def test_ghali_elegant_is_an_official_alias_not_a_duplicate_identity(self):
        matches = [
            p for p in CATALOG["products"]
            if p.get("brand_name") == "Zimaya"
            and "Ghali Elegant" in p.get("aliases", [])
        ]
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["canonical_name"], "Ghali Elegante")
        self.assertEqual(matches[0]["source_url"], "https://us.zimayaperfumes.com/products/ghali-elegante")
        self.assertEqual(matches[0]["concentration"], "Eau de Parfum")

    def test_new_identities_are_registered_in_their_existing_brand_families(self):
        families = {f["family_id"]: f for f in REGISTRY["families"]}
        for brand, rows in EXPECTED.items():
            family_id = "swiss_arabian_catalog" if brand == "Swiss Arabian" else "zimaya_catalog"
            registered = {
                p["canonical_name"] for p in families[family_id]["products"]
            }
            for name in rows:
                with self.subTest(brand=brand, name=name):
                    self.assertIn(name, registered)

    def test_no_new_canonical_duplicates_by_brand_and_name(self):
        keys = [
            (p.get("brand_name", "").casefold(), p.get("canonical_name", "").casefold())
            for p in CATALOG["products"]
        ]
        self.assertEqual(len(keys), len(set(keys)))


if __name__ == "__main__":
    unittest.main()
