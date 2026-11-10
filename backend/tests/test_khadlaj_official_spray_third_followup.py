"""Regression coverage for fifteen Khadlaj official EDP product variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = {
    "Cashmere Warm Oud": {"id": "SH-KHADLAJ-SPRAY-HARVEST-102", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107974781", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-102-100-EDP", "url": "https://khadlaj-perfumes.com/products/cashmere-warm-oud-100-ml-edp-spray-for-men-women"},
    "Cashmere Sunshine Musk": {"id": "SH-KHADLAJ-SPRAY-HARVEST-103", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107974798", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-103-100-EDP", "url": "https://khadlaj-perfumes.com/products/cashmere-sunshine-musk100-ml-edp-spray-for-men-women"},
    "Ghadeer Silver": {"id": "SH-KHADLAJ-SPRAY-HARVEST-107", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107977010", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-107-100-EDP", "url": "https://khadlaj-perfumes.com/products/ghadeer-silver-100-ml-edp-spray-for-men-women-best-edp-perfume-dubai-uae"},
    "Infini Absolute": {"id": "SH-KHADLAJ-SPRAY-HARVEST-101", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975481", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-101-100-EDP", "url": "https://khadlaj-perfumes.com/products/infini-absolute-edp-spray-100-ml"},
    "Sensuous Night": {"id": "SH-KHADLAJ-SPRAY-HARVEST-105", "size": 100, "concentration": "Eau de Parfum", "gtin": None, "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-105-100-EDP", "url": "https://khadlaj-perfumes.com/products/sensous-night-edp-spray-shop-online-best-price-in-dubai-uae"},
    "Oud Pour Noble": {"id": "SH-KHADLAJ-SPRAY-HARVEST-096", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107971025", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-096-100-000", "url": "https://khadlaj-perfumes.com/products/oud-pour-noble-spray-shop-online-best-price-in-dubai-uae"},
    "Oud Pour Shaikh": {"id": "SH-KHADLAJ-SPRAY-HARVEST-098", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107970608", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-098-100-EDP", "url": "https://kw.khadlaj-perfumes.com/products/oud-pour-shaikh-spray-shop-online-best-price-in-dubai-uae"},
    "Oud Pour Rouge": {"id": "SH-KHADLAJ-SPRAY-HARVEST-099", "size": 100, "concentration": "Eau de Parfum", "gtin": None, "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-099-100-EDP", "url": "https://khadlaj-perfumes.com/products/oud-pour-rouge-spray-shop-online-best-price-in-dubai-uae"},
    "Rose Couture": {"id": "SH-KHADLAJ-SPRAY-HARVEST-115", "size": 100, "concentration": "Eau de Parfum", "gtin": None, "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-115-100-EDP", "url": "https://khadlaj-perfumes.com/collections/perfumes-spray/products/rose-couture-edp-spray-shop-online-best-price-in-dubai-uae"},
    "Musk Pour Narcis": {"id": "SH-KHADLAJ-SPRAY-HARVEST-097", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107970592", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-097-100-EDP", "url": "https://kw.khadlaj-perfumes.com/products/musk-pour-narcis-spray-shop-online-best-price-in-dubai-uae"},
    "Oud Pour Blueberry": {"id": "SH-KHADLAJ-SPRAY-HARVEST-100", "size": 100, "concentration": "Eau de Parfum", "gtin": None, "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-100-100-EDP", "url": "https://khadlaj-perfumes.com/collections/oud-pour-series-collection-shop-for-captivating-niche-fragrances/products/oud-pour-blueberry-spray-shop-online-best-price-in-dubai-uae"},
    "Magnate Noble": {"id": "SH-KHADLAJ-SPRAY-HARVEST-110", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975054", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-110-100-EDP", "url": "https://khadlaj-perfumes.com/products/magnate-noble-100ml-edp-spray"},
    "Magnate Premier": {"id": "SH-KHADLAJ-SPRAY-HARVEST-111", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975061", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-111-100-EDP", "url": "https://khadlaj-perfumes.com/collections/new-launches-top-fragrances-to-shop-online/products/magnate-premier-100ml-edp-spray"},
    "Musk Al Sabah": {"id": "SH-KHADLAJ-SPRAY-HARVEST-108", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107977027", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-108-100-000", "url": "https://khadlaj-perfumes.com/products/musk-al-sabah-100-ml-edp-spray-buy-online-best-price-dubai-uae"},
    "Oud Al Sabah": {"id": "SH-KHADLAJ-SPRAY-HARVEST-109", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107977034", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-109-100-000", "url": "https://khadlaj-perfumes.com/collections/all-products-exception/products/oud-al-sabah-100-ml-edp-spray-dubai-uae-amber-oud-fragrance"},
}

class KhadlajOfficialSprayThirdFollowupTests(unittest.TestCase):
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
