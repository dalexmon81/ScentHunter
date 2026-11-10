"""Regression coverage for eight remaining Khadlaj official product variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = {
    "Sawaar Vanille Blanc": {"id": "SH-KHADLAJ-24969f48", "size": 100, "concentration": None, "gtin": "6298043070768", "variant_id": "SHV-SH-KHADLAJ-24969f48-100-UNSPECIFIED", "url": "https://khadlaj-perfumes.com/products/sawaar-vanille-blanc-100-ml-eau-de-parfum-spray-for-women"},
    "Maison L'Imaginaire": {"id": "SH-KHADLAJ-SPRAY-HARVEST-061", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107976044", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-061-100-EDP", "url": "https://khadlaj-perfumes.com/collections/premium-colllection/products/maison-l-imaginaire-100ml-edp-spray"},
    "Saqr Al Badiya": {"id": "SH-KHADLAJ-SPRAY-HARVEST-062", "size": 100, "concentration": None, "gtin": "6291107978765", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-062-100-UNSPECIFIED", "url": "https://khadlaj-perfumes.com/products/saqr-al-badiya-extrait-de-parfum-spray-for-men-with-aquatic-notes-shop-online-dubai-uae"},
    "Musk Pure Musk Blend Creation of Iqbal": {"id": "SH-KHADLAJ-04832397", "canonical_name": "Musk Pure Musk Blend", "size": 60, "concentration": "Eau de Parfum", "gtin": "6291107978154", "variant_id": "SHV-SH-KHADLAJ-04832397-60-000", "url": "https://khadlaj-perfumes.com/products/musk-pure-musk-blend-creation-of-iqbal-65-ml-edp-spray-perfume-for-men-and-women-online-dubai-uae"},
    "Wild Indonesian Oud": {"id": "SH-KHADLAJ-SPRAY-HARVEST-094", "size": 60, "concentration": "Eau de Parfum", "gtin": "6291107974620", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-094-60-EDP", "url": "https://khadlaj-perfumes.com/products/wild-indonesian-oud-spray-shop-online-best-price-in-dubai-uae"},
    "Shahi Oud": {"id": "SH-KHADLAJ-SPRAY-HARVEST-113", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107971032", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-113-100-000", "url": "https://khadlaj-perfumes.com/products/shahi-oud-edp-spray-shop-online-best-price-in-dubai-uae"},
    "Barwaaz Solid Grey": {"id": "SH-KHADLAJ-SPRAY-HARVEST-114", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107974392", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-114-100-EDP", "url": "https://khadlaj-perfumes.com/products/barwaaz-solid-grey-spray-shop-online-best-price-in-dubai-uae"},
    "Musk Couture": {"id": "SH-KHADLAJ-SPRAY-HARVEST-116", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107976976", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-116-100-EDP", "url": "https://khadlaj-perfumes.com/collections/unisex-1/products/musk-couture-edp-spray-100-ml-best-perfume-for-men-and-women-in-dubai-uae"},
}

class KhadlajOfficialSprayFourthFollowupTests(unittest.TestCase):
    def test_existing_identities_have_official_product_page_provenance(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                canonical_name = expected.get("canonical_name", name)
                products = [p for p in CATALOG["products"] if p.get("brand") == "Khadlaj" and p.get("canonical_name") == canonical_name and p.get("product_id") == expected["id"]]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product["identity_status"], "source_verified_name")
                if name != canonical_name:
                    self.assertIn(name, product.get("aliases", []))
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["url"])
                self.assertEqual(product["formats_ml"], [expected["size"]])
                if expected["concentration"]:
                    self.assertEqual(product["concentration"], expected["concentration"])
                else:
                    self.assertNotIn("concentration", product)

    def test_variant_attributes_preserve_unknown_concentration_instead_of_guessing(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == expected["id"]]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["variant_id"], expected["variant_id"])
                self.assertEqual(variant["size_ml"], expected["size"])
                self.assertEqual(variant["gtin"], expected["gtin"])
                self.assertEqual(variant["source_url"], expected["url"])
                self.assertEqual(variant["source_evidence_url"], expected["url"])
                if expected["concentration"]:
                    self.assertEqual(variant["concentration"], expected["concentration"])
                else:
                    self.assertNotIn("concentration", variant)

    def test_family_registry_formats_match_official_product_pages(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                product = next(p for p in CATALOG["products"] if p.get("product_id") == expected["id"])
                family = next(f for f in REGISTRY["families"] if f.get("family_id") == product["family_id"])
                rows = [p for p in family["products"] if p.get("canonical_name") == canonical_name]
                self.assertEqual(len(rows), 1)
                self.assertIn(expected["size"], rows[0].get("formats_ml", []))

if __name__ == "__main__":
    unittest.main()
