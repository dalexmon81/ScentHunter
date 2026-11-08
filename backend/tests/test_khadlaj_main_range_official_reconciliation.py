"""Regression tests for Khadlaj main-range official product reconciliation."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Bleu Glace": {
        "size": 100,
        "conc": "Extrait de Parfum",
        "url": "https://khadlaj-perfumes.com/products/bleu-glace-100-ml-extrait-de-parfum-for-men-fresh-fragrance-online-dubai-uae"
    },
    "Code Marron Oud": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/code-marron-oud-spray-shop-online-best-price-in-dubai-uae"
    },
    "Code Rouge Amour": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/code-rouge-amour-spray-shop-online-best-price-in-dubai-uae"
    },
    "Code Verde Sublime": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/code-verde-sublime-spray-shop-online-best-price-in-dubai-uae"
    },
    "Code Viola Nectar": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/code-viola-nectar-spray-shop-online-best-price-in-dubai-uae"
    },
    "Gaith": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/extrait-de-parfum-range/products/gaith-100-ml-edp-spray-men-perfumes-dubai-uae"
    },
    "Hareem Al Sultan Blue": {
        "size": 35,
        "conc": "Perfume Oil",
        "url": "https://khadlaj-perfumes.com/collections/khadlaj-discover-more/products/hareem-al-sultan-blue-35ml"
    },
    "Maya": {
        "size": 20,
        "conc": "Perfume Oil",
        "url": "https://khadlaj-perfumes.com/products/khadlaj-maya-20-ml-alcohol-free-perfume-attars-online-dubai-uae"
    },
    "Mocha Latte": {
        "size": 100,
        "conc": "Extrait de Parfum",
        "url": "https://khadlaj-perfumes.com/products/mocha-latte-100-ml-extrait-de-parfum-spray-for-unisex-coffee-fragrance-dubai-uae"
    },
    "Rose And Romance": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/discover-more/products/rose-and-romance-spray-shop-online-best-price-in-dubai-uae"
    },
    "Shiyaaka Men": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/products/shiyaaka-for-men-spray-shop-online-best-price-in-dubai-uae"
    },
    "Uno Durable": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/best-selling-perfumes/products/uno-durable-edp-spray-shop-online-best-price-in-dubai-uae"
    },
    "Uno Intimo": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume/products/uno-intimo-edp-spray-shop-online-best-price-in-dubai-uae"
    },
    "Uno Lusso": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/all/products/uno-lusso-edp-spray-shop-online-best-price-in-dubai-uae"
    },
    "Uno Sensuale": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/women-perfume/products/uno-sensuale-edp-spray-shop-online-best-price-in-dubai-uae"
    },
    "Wow Oud": {
        "size": 100,
        "conc": "Eau de Parfum",
        "url": "https://khadlaj-perfumes.com/collections/extrait-de-parfum-range/products/wow-oud-100-ml-edp-spray"
    }
}


class KhadlajMainRangeOfficialReconciliationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = {
            p["canonical_name"]: p
            for p in CATALOG["products"]
            if p.get("brand_name") == "Khadlaj"
        }
        cls.variants = CATALOG["variants"]
        cls.family = next(
            f for f in REGISTRY["families"]
            if f.get("family_id") == "khadlaj_catalog"
        )

    def test_all_registry_gaps_are_promoted_from_individual_official_pages(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["url"])
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["formats_ml"], [expected["size"]])

    def test_variants_match_official_size_and_concentration(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = self.products[name]
                matches = [
                    v for v in self.variants
                    if v["product_id"] == product["product_id"]
                ]
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]["size_ml"], expected["size"])
                self.assertEqual(matches[0]["source_url"], expected["url"])
                if expected["conc"] is None:
                    self.assertNotIn("concentration", matches[0])
                    self.assertNotIn("concentration", product)
                else:
                    self.assertEqual(matches[0]["concentration"], expected["conc"])

    def test_registry_formats_are_aligned(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                row = next(p for p in self.family["products"] if p["canonical_name"] == name)
                self.assertIn(expected["size"], row.get("formats_ml", []))

    def test_sensuos_night_is_an_alias_of_existing_sensuous_night_identity(self):
        product = self.products["Sensuous Night"]
        self.assertIn("Sensuos Night", product["aliases"])
        self.assertEqual(
            product["source_url"],
            "https://khadlaj-perfumes.com/collections/perfumes-spray",
        )
        self.assertEqual(
            product["source_evidence_url"],
            "https://khadlaj-perfumes.com/collections/flash-sale/products/sensous-night-edp-spray-shop-online-best-price-in-dubai-uae",
        )
        family = next(
            f for f in REGISTRY["families"]
            if f["family_id"] == "khadlaj_official_perfume_sprays_2026_11"
        )
        rows = [p for p in family["products"] if p["canonical_name"] == "Sensuous Night"]
        self.assertEqual(len(rows), 1)
        self.assertIn("Sensuos Night", rows[0]["aliases"])

    def test_catalog_product_and_variant_ids_are_unique_and_references_valid(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in self.variants]
        known_products = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertTrue(all(v["product_id"] in known_products for v in self.variants))


if __name__ == "__main__":
    unittest.main()
