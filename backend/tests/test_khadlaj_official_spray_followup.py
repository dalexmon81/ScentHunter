"""Regression coverage for twelve more Khadlaj official product variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))
EXPECTED = {
    "Biscotti Caramel Pop": {"id": "SH-KHADLAJ-BISCOTTI-CARAMEL-POP", "size": 100, "concentration": "Extrait de Parfum", "gtin": "6291107979953", "variant_id": "SHV-SH-KHADLAJ-BISCOTTI-CARAMEL-POP-100-EXTRAIT", "url": "https://khadlaj-perfumes.com/products/biscotti-caramel-pop-100-ml-extrait-de-parfum-spray-for-men-women-gourmand-lovers-fragrance-dubai-uae", "family": "khadlaj_catalog"},
    "Stellar Musk": {"id": "SH-KHADLAJ-81775c55", "size": 100, "concentration": "Eau de Parfum", "gtin": null, "variant_id": "SHV-SH-KHADLAJ-81775c55-100-EDP", "url": "https://khadlaj-perfumes.com/collections/women-perfume/products/stellar-musk-100-ml-edp-spray-for-women", "family": "khadlaj_catalog"},
    "Stellar Oud": {"id": "SH-KHADLAJ-b8b265ff", "size": 100, "concentration": "Eau de Parfum", "gtin": null, "variant_id": "SHV-SH-KHADLAJ-b8b265ff-100-EDP", "url": "https://khadlaj-perfumes.com/products/stellar-oud-100-ml-edp-spray-for-men-women", "family": "khadlaj_catalog"},
    "Opus Reborn": {"id": "SH-KHADLAJ-SPRAY-HARVEST-063", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107978130", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-063-100-EDP", "url": "https://khadlaj-perfumes.com/products/opus-reborn-100-ml-edp-spray-for-men-fragrance-to-shop-online-dubai-uae", "family": "khadlaj_official_perfume_sprays_2026_11"},
    "Karus Secret Musk": {"id": "SH-KHADLAJ-SPRAY-HARVEST-087", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975870", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-087-100-EDP", "url": "https://khadlaj-perfumes.com/products/karus-secret-musk-100-ml-edp-spray", "family": "khadlaj_official_perfume_sprays_2026_11"},
    "Karus Blu Spice": {"id": "SH-KHADLAJ-SPRAY-HARVEST-086", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975856", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-086-100-EDP", "url": "https://khadlaj-perfumes.com/products/karus-blu-spice-100-ml-edp-spray", "family": "khadlaj_official_perfume_sprays_2026_11"},
    "Karus Oud Fire": {"id": "SH-KHADLAJ-SPRAY-HARVEST-088", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975863", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-088-100-EDP", "url": "https://khadlaj-perfumes.com/products/karus-oud-fire-100-ml-edp-spray", "family": "khadlaj_official_perfume_sprays_2026_11"},
    "Valor Mystique": {"id": "SH-KHADLAJ-SPRAY-HARVEST-079", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975993", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-079-100-EDP", "url": "https://khadlaj-perfumes.com/products/valor-mystique-100-ml-edp-spray", "family": "khadlaj_official_perfume_sprays_2026_11"},
    "Valor Honor": {"id": "SH-KHADLAJ-SPRAY-HARVEST-080", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975962", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-080-100-EDP", "url": "https://khadlaj-perfumes.com/collections/mens-perfumes/products/valor-honor-100-ml-edp-spray", "family": "khadlaj_official_perfume_sprays_2026_11"},
    "Valor Chivalry": {"id": "SH-KHADLAJ-SPRAY-HARVEST-081", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975986", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-081-100-EDP", "url": "https://khadlaj-perfumes.com/collections/mens-perfumes/products/valor-chivalry-100-ml-edp-spray", "family": "khadlaj_official_perfume_sprays_2026_11"},
    "Empire Crown": {"id": "SH-KHADLAJ-SPRAY-HARVEST-084", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975887", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-084-100-000", "url": "https://khadlaj-perfumes.com/products/empire-crown-100-ml-edp-spray-best-perfume-spray-for-men-online-dubai-uae", "family": "khadlaj_official_perfume_sprays_2026_11"},
    "Empire Regent": {"id": "SH-KHADLAJ-SPRAY-HARVEST-085", "size": 100, "concentration": "Eau de Parfum", "gtin": "6291107975900", "variant_id": "SHV-SH-KHADLAJ-SPRAY-HARVEST-085-100-000", "url": "https://khadlaj-perfumes.com/products/empire-regent-100-ml-edp-spray-luxury-perfume-for-men-and-women-dubai-uae", "family": "khadlaj_official_perfume_sprays_2026_11"},
}

class KhadlajOfficialSprayFollowupTests(unittest.TestCase):
    def test_existing_product_identity_and_official_detail_provenance(self):
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

    def test_one_variant_per_existing_identity_and_official_page_evidence(self):
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
                if expected["gtin"] is not None:
                    self.assertEqual(variant["gtin"], expected["gtin"])
                else:
                    self.assertNotIn("gtin", variant)

    def test_family_registry_formats_follow_product_family(self):
        for name, expected in EXPECTED.items():
            with self.subTest(product=name):
                family = next(f for f in REGISTRY["families"] if f.get("family_id") == expected["family"])
                rows = [p for p in family["products"] if p.get("canonical_name") == name]
                self.assertEqual(len(rows), 1)
                self.assertIn(expected["size"], rows[0].get("formats_ml", []))

if __name__ == "__main__":
    unittest.main()
