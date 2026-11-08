"""Regression coverage for Lattafa official product identities missing from the seed."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Ana Abiyedh Rouge": {
        "size": 60,
        "conc": "Eau de Parfum",
        "url": "https://lattafa.com/product/ana-abiyedh-rouge/",
        "evidence": "https://www.lattafa-usa.com/products/ana-abiyedh-rouge-set"
    },
    "Rave Now White": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://lattafa.com/product/rave-now-white/",
        "evidence": "https://lattafa.com/product/rave-now-white/"
    },
    "24 Carat White Gold": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://lattafa.com/product/24-carat-white-gold/",
        "evidence": "https://www.lattafa-usa.com/products/24-carat-white-gold"
    },
    "Ajayeb Dubai Portrait": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://lattafa.com/product/ajayeb-dubai-portrait/",
        "evidence": "https://www.lattafa-usa.com/products/ajayab-dubai"
    },
    "Al Dur Al Maknoon Silver": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://lattafa.com/product/al-dur-al-maknoon-silver/",
        "evidence": "https://www.lattafa-usa.com/products/al-dur-al-maknoon-silver"
    },
    "Al Nashama": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://www.lattafa-usa.com/products/al-nashama",
        "evidence": "https://www.lattafa-usa.com/products/al-nashama"
    },
    "Ameer Al Oud Intense": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://lattafa.com/product/ameer-al-oudh-intense/",
        "evidence": "https://www.lattafa-usa.com/products/ameer-al-oud-intense"
    },
    "Ana Abiyedh Coral": {
        "size": 60,
        "conc": "Eau de Parfum",
        "url": "https://lattafa.com/product/ana-abiyedh-coral/",
        "evidence": "https://www.lattafa-usa.com/products/ana-abiyedh-coral"
    },
    "GMG Whipped Pleasure": {
        "size": 75,
        "conc": "Eau de Parfum",
        "url": "https://lattafa.com/product/whipped-pleasure/",
        "evidence": "https://www.lattafa-usa.com/products/whipped-pleasure"
    }
}


class LattafaOfficialMissingIdentitiesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Lattafa"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "lattafa_catalog"
        )

    def test_all_nine_registry_gaps_have_official_product_records(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["evidence"])
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["formats_ml"], [expected["size"]])
                self.assertEqual(product["concentration"], expected["conc"])

    def test_each_product_has_one_officially_sized_edp_variant(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                matches = [
                    v for v in self.variants
                    if v["product_id"] == product["product_id"]
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["size_ml"], expected["size"])
                self.assertEqual(matches[0]["concentration"], expected["conc"])
                self.assertEqual(matches[0]["source_url"], expected["url"])

    def test_registry_formats_are_aligned(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                row = next(p for p in self.family["products"] if p["canonical_name"] == name)
                self.assertIn(expected["size"], row.get("formats_ml", []))

    def test_public_spelling_aliases_are_preserved(self):
        self.assertIn("Ajayab Dubai Portrait", self.products["Ajayeb Dubai Portrait"]["aliases"])
        self.assertIn("Ameer Al Oudh Intense", self.products["Ameer Al Oud Intense"]["aliases"])
        self.assertIn("Whipped Pleasure", self.products["GMG Whipped Pleasure"]["aliases"])

    def test_product_and_variant_ids_are_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in self.variants]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))


if __name__ == "__main__":
    unittest.main()
