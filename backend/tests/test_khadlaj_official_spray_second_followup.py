"""Regression coverage for sixteen Khadlaj official product-page variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = {
    "Hareem Al Sultan": {"id": "SH-KHADLAJ-SPRAY-HARVEST-059", "size": 75, "concentration": "Eau de Parfum", "gtin": "6291107976556", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-059-75-EDP", "url": "https://khadlaj-perfumes.com/collections/unisex-1/products/tiktk-viral-hareem-al-sultan-perfume-in-75-ml-edp-spray-by-khadlaj-dubai", "sku_note": None},
    "Azure Velvet": {"id": "SH-KHADLAJ-SPRAY-HARVEST-060", "size": 100, "concentration": "Extrait de Parfum", "gtin": "6291107978802", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-060-100-EXTRAIT", "url": "https://khadlaj-perfumes.com/collections/unisex-1/products/azure-velvet-100-ml-extrait-de-parfum-unisex-fragrance-to-buy-online-dubai-uae", "sku_note": None},
    "Le Prestige King": {"id": "SH-KHADLAJ-SPRAY-HARVEST-068", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975955", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-068-100-EDP", "url": "https://khadlaj-perfumes.com/collections/unisex-1/products/le-prestige-king-100-ml-edp-spray", "sku_note": None},
    "The Proposal Date Night": {"id": "SH-KHADLAJ-SPRAY-HARVEST-069", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291197975818", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-069-100-EDP", "url": "https://khadlaj-perfumes.com/products/the-proposal-date-night-100-ml-edp-spray", "sku_note": None},
    "The Proposal Special Occasion": {"id": "SH-KHADLAJ-SPRAY-HARVEST-073", "size": 100, "concentration": "Eau de Parfum", "gtin": None, "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-073-100-EDP", "url": "https://khadlaj-perfumes.com/collections/women-perfume/products/the-proposal-special-occasion-100-ml-edp-spray", "sku_note": "Official page displays a 12-digit SKU; not stored as GTIN."},
    "25 Experience": {"id": "SH-KHADLAJ-SPRAY-HARVEST-074", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975351", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-074-100-EDP", "url": "https://khadlaj-perfumes.com/collections/khadlaj-25-eau-de-parfum-collection/products/khadlaj-25-experience-100-ml-edp-spray", "sku_note": None},
    "25 Trust": {"id": "SH-KHADLAJ-SPRAY-HARVEST-075", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975399", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-075-100-EDP", "url": "https://khadlaj-perfumes.com/products/buy-khadlaj-25-trust-100-ml-edp-spray-best-gourmand-perfume-for-women", "sku_note": None},
    "25 Loyalty": {"id": "SH-KHADLAJ-SPRAY-HARVEST-076", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975382", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-076-100-EDP", "url": "https://khadlaj-perfumes.com/products/khadlaj-25-loyalty-100-ml-edp-spray-best-women-perfume-to-shop-online-dubai-uae", "sku_note": None},
    "25 Heritage": {"id": "SH-KHADLAJ-SPRAY-HARVEST-077", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975368", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-077-100-EDP", "url": "https://khadlaj-perfumes.com/products/khadlaj-25-heritage-100-ml-edp-spray", "sku_note": None},
    "25 Integrity": {"id": "SH-KHADLAJ-SPRAY-HARVEST-078", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975375", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-078-100-EDP", "url": "https://khadlaj-perfumes.com/collections/unisex-1/products/khadlaj-25-integrity-100-ml-edp-spray", "sku_note": None},
    "Karus Amber Gold": {"id": "SH-KHADLAJ-SPRAY-HARVEST-089", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975849", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-089-100-EDP", "url": "https://khadlaj-perfumes.com/products/karus-amber-gold-100-ml-edp-spray", "sku_note": None},
    "Maison Creation De Reve": {"id": "SH-KHADLAJ-SPRAY-HARVEST-090", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107976037", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-090-100-EDP", "url": "https://khadlaj-perfumes.com/products/maison-creation-de-reve-100ml", "sku_note": None},
    "Maison Epoque Artistique": {"id": "SH-KHADLAJ-SPRAY-HARVEST-091", "size": 100, "concentration": "Eau de Parfum", "gtin": None, "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-091-100-EDP", "url": "https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/maison-epoque-artistique-100ml-edp-spray", "sku_note": None},
    "Maison L'Or Noir": {"id": "SH-KHADLAJ-SPRAY-HARVEST-092", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107976020", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-092-100-EDP", "url": "https://khadlaj-perfumes.com/products/maison-l-or-noir-100ml-edp-spray", "sku_note": None},
    "Maison Flor Oud": {"id": "SH-KHADLAJ-SPRAY-HARVEST-093", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107976068", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-093-100-EDP", "url": "https://khadlaj-perfumes.com/products/maison-flor-oud-100ml-edp-spray", "sku_note": None},
    "Mystical Indian Oud Pure": {"id": "SH-KHADLAJ-SPRAY-HARVEST-095", "size": 60, "concentration": "Eau de Parfum", "gtin": "6291107974613", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-095-60-EDP", "url": "https://khadlaj-perfumes.com/products/mystical-indian-oud-pure-60-ml-edp-spray", "sku_note": None},
}

class KhadlajOfficialSpraySecondFollowupTests(unittest.TestCase):
    def test_existing_product_identities_have_official_detail_provenance(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                products = [p for p in CATALOG["products"] if p.get("brand") == "Khadlaj" and p.get("canonical_name") == name and p.get("product_id") == expected["id"]]
                self.assertEqual(len(products), 1)
                product = products[0]
                self.assertEqual(product["identity_status"], "source_verified_name")
                self.assertEqual(product["source_url"], expected["url"])
                self.assertEqual(product["source_product_url"], expected["url"])
                self.assertEqual(product["source_evidence_url"], expected["url"])
                self.assertEqual(product["concentration"], expected["concentration"])
                self.assertEqual(product["formats_ml"], [expected["size"]])

    def test_each_product_has_one_variant_with_official_attributes(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                variants = [v for v in CATALOG["variants"] if v.get("product_id") == expected["id"]]
                self.assertEqual(len(variants), 1)
                variant = variants[0]
                self.assertEqual(variant["variant_id"], expected["variant_id"])
                self.assertEqual(variant["size_ml"], expected["size"])
                self.assertEqual(variant["concentration"], expected["concentration"])
                self.assertEqual(variant["source_url"], expected["url"])
                self.assertEqual(variant["source_evidence_url"], expected["url"])
                if expected["gtin"]:
                    self.assertEqual(variant["gtin"], expected["gtin"])
                else:
                    self.assertNotIn("gtin", variant)

    def test_official_spray_family_registry_has_the_verified_formats(self):
        family = next(f for f in REGISTRY["families"] if f.get("family_id") == "khadlaj_official_perfume_sprays_2026_11")
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertIn(expected["size"], rows[0].get("formats_ml", []))

if __name__ == "__main__":
    unittest.main()
