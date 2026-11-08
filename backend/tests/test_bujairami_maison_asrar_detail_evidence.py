"""Official individual-detail evidence for Bujairami and Maison Asrar."""
import json
import unittest
from pathlib import Path

CATALOG = json.loads((Path(__file__).resolve().parents[1] / "product_catalog.json").read_text(encoding="utf-8"))

BUJAIRAMI = {
    "Gold Coast Shiraz": ("https://bujairami.eu/product/gold-coast-shiraz/", "Eau de Parfum"),
    "G’Day": ("https://bujairami.eu/product/gday/", "Extrait de Parfum"),
    "Midnight in Melbourne": ("https://bujairami.eu/product/midnight-in-melbourne/", "Eau de Parfum"),
    "Sunrise in Sydney": ("https://bujairami.eu/product/sunrise-in-sydney/", "Eau de Parfum"),
}

class BujairamiMaisonAsrarDetailEvidenceTests(unittest.TestCase):
    def product(self, brand, name):
        matches = [p for p in CATALOG["products"] if (p.get("brand_name") or p.get("brand")) == brand and p.get("canonical_name") == name]
        self.assertEqual(len(matches), 1, f"{brand}/{name}")
        return matches[0]

    def test_bujairami_official_detail_pages_and_100ml_variants(self):
        for name, (url, concentration) in BUJAIRAMI.items():
            with self.subTest(name=name):
                p = self.product("Bujairami", name)
                self.assertEqual(p["identity_status"], "source_verified_name")
                self.assertEqual(p["source_url"], url)
                self.assertEqual(p["source_evidence_url"], url)
                self.assertEqual(p["concentration"], concentration)
                self.assertEqual(p["formats_ml"], [100])
                variants = [v for v in CATALOG["variants"] if v["product_id"] == p["product_id"]]
                self.assertEqual(len(variants), 1)
                self.assertEqual(variants[0]["size_ml"], 100)
                self.assertEqual(variants[0]["concentration"], concentration)
                self.assertEqual(variants[0]["source_url"], url)

    def test_maison_asrar_ameer_has_individual_official_page_without_guessed_format(self):
        p = self.product("Maison Asrar", "Ameer")
        self.assertEqual(p["identity_status"], "source_verified_name")
        self.assertEqual(p["source_url"], "https://maisonasrar.com/products/ameer")
        self.assertEqual(p["source_evidence_url"], "https://maisonasrar.com/products/ameer")
        self.assertNotIn("formats_ml", p)
        self.assertEqual([v for v in CATALOG["variants"] if v["product_id"] == p["product_id"]], [])

    def test_product_and_variant_ids_remain_unique(self):
        product_ids = [p["product_id"] for p in CATALOG["products"]]
        variant_ids = [v["variant_id"] for v in CATALOG["variants"]]
        self.assertEqual(len(product_ids), len(set(product_ids)))
        self.assertEqual(len(variant_ids), len(set(variant_ids)))

    def test_no_commercial_offer_data_is_added(self):
        audited = {p["product_id"] for p in CATALOG["products"] if (p.get("brand_name") or p.get("brand")) in {"Bujairami", "Maison Asrar"}}
        forbidden = {"price", "stock", "availability", "shipping_cost", "store_url"}
        for item in CATALOG["products"] + CATALOG["variants"]:
            if item.get("product_id") in audited:
                self.assertTrue(forbidden.isdisjoint(item))

if __name__ == "__main__":
    unittest.main()
