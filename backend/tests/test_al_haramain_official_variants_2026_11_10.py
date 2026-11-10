"""Seven Al Haramain variants verified on the brand's official EU storefront."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Amber Oud Bleu Edition": {
        "product_id": "SH-AL-HARAMAIN-0cf10f35",
        "formats_ml": [60, 200],
        "concentration": "Eau de Parfum",
        "variants": {
            60: ("SHV-SH-AL-HARAMAIN-0cf10f35-60-EDP", "https://shop.alharamainperfumes.com/eu/amber-oud-bleu-edition.html"),
            200: ("SHV-SH-AL-HARAMAIN-0cf10f35-200-EDP", "https://shop.alharamainperfumes.com/eu/amber-oud-bleu-edition-200ml.html"),
        },
    },
    "Amber Oud Tobacco Edition": {
        "product_id": "SH-AL-HARAMAIN-27b89224",
        "formats_ml": [100, 200],
        "concentration": "Eau de Parfum",
        "variants": {
            100: ("SHV-SH-AL-HARAMAIN-27b89224-100-EDP", "https://shop.alharamainperfumes.com/eu/amber-oud-tobacco-100ml.html"),
            200: ("SHV-SH-AL-HARAMAIN-27b89224-200-000", "https://shop.alharamainperfumes.com/eu/haramain-amber-oud-200ml-spray-tobacco-edition.html"),
        },
    },
    "L'Aventure Femme": {
        "product_id": "SH-AL-HARAMAIN-4455529b",
        "formats_ml": [30, 100],
        "concentration": "Eau de Parfum",
        "variants": {
            30: ("SHV-SH-AL-HARAMAIN-4455529b-30-EDP", "https://shop.alharamainperfumes.com/eu/al-haramain-l-aventure-femme-30ml.html"),
            100: ("SHV-SH-AL-HARAMAIN-4455529b-100-EDP", "https://shop.alharamainperfumes.com/eu/haramain-l-aventure-femme-100ml-eau-de-parfum.html"),
        },
    },
    "Junoon": {
        "product_id": "SH-AL-HARAMAIN-ff023f21",
        "formats_ml": [75],
        "concentration": "Eau de Parfum",
        "variants": {
            75: ("SHV-SH-AL-HARAMAIN-ff023f21-75-EDP", "https://shop.alharamainperfumes.com/eu/haramain-junoon.html"),
        },
    },
    "Black Oud": {
        "product_id": "SH-AL-HARAMAIN-838494c5",
        "formats_ml": [100],
        "concentration": "Extrait de Parfum",
        "variants": {
            100: ("SHV-SH-AL-HARAMAIN-838494c5-100-EXTRAIT", "https://shop.alharamainperfumes.com/eu/haramain-black-oud-spray-100ml.html"),
        },
    },
}


class AlHaramainOfficialVariantsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.products = CATALOG["products"]
        cls.variants = CATALOG["variants"]
        cls.family = next(
            family for family in REGISTRY["families"]
            if family.get("family_id") == "al_haramain_catalog"
        )

    def test_product_variants_match_official_product_pages(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in self.products if p.get("product_id") == expected["product_id"])
                self.assertEqual(product["brand"], "Al Haramain")
                self.assertEqual(product["canonical_name"], name)
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["formats_ml"], expected["formats_ml"])
                self.assertEqual(product["concentration"], expected["concentration"])
                for size, (variant_id, url) in expected["variants"].items():
                    variant = next(
                        v for v in self.variants
                        if v.get("product_id") == expected["product_id"]
                        and v.get("size_ml") == size
                    )
                    self.assertEqual(variant["variant_id"], variant_id)
                    self.assertEqual(variant["concentration"], expected["concentration"])
                    self.assertEqual(variant["source_evidence_url"], url)
                    self.assertNotIn("gtin", variant)

    def test_family_registry_formats_match_verified_variants(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [p for p in self.family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].get("formats_ml"), expected["formats_ml"])

    def test_global_catalog_integrity_and_offer_separation(self):
        product_ids = [p.get("product_id") for p in self.products]
        variant_ids = [v.get("variant_id") for v in self.variants]
        gtins = [v.get("gtin") for v in self.variants if v.get("gtin")]
        tuples = [(v.get("product_id"), v.get("size_ml"), v.get("concentration")) for v in self.variants]
        known_products = set(product_ids)
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))
        self.assertEqual(len(gtins), len(set(gtins)))
        self.assertEqual(len(tuples), len(set(tuples)))
        self.assertTrue(all(v.get("product_id") in known_products for v in self.variants))
        offer_fields = {"price", "stock", "availability", "shipping_cost", "store_url", "retailer"}
        for variant in self.variants:
            self.assertTrue(offer_fields.isdisjoint(variant))


if __name__ == "__main__":
    unittest.main()
