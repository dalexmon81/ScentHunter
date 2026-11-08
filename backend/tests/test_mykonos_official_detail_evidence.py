"""Official detail-page evidence regression for Mykonos catalog identities."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED_DETAIL_PAGES = {
    "Invade": "https://officialmykonos.com/products/mykonos-x-setiawanade-invade-extrait-de-parfum-50ml",
    "Glitch": "https://officialmykonos.com/products/mykonos-x-setiawanade-glitch-extrait-de-parfum-50ml",
    "Empire x RRQ": "https://officialmykonos.com/products/mykonos-x-rrq-empire-extrait-de-parfum-50ml-100ml",
    "MyEgo": "https://officialmykonos.com/products/mykonos-x-alterego-myego-extrait-de-parfum-50ml-100ml",
    "Xoxo Rosy": "https://officialmykonos.com/products/mykonos-xoxo-rosy-edp-50ml",
    "Verve": "https://officialmykonos.com/products/mykonos-verve-extrait-de-parfum-when-in-paris-edp-50ml",
    "Vanilla Clouds": "https://officialmykonos.com/products/mykonos-vanilla-clouds-extrait-de-parfum-50ml-1",
    "Stilettos": "https://officialmykonos.com/products/mykonos-stilettos-edp-50ml",
    "Sorrento": "https://officialmykonos.com/products/mykonos-sorrento-extrait-de-parfum-50ml-100ml",
    "Slow Living": "https://officialmykonos.com/products/mykonos-slow-living-edp-50ml",
    "Silent Whisper": "https://officialmykonos.com/products/mykonos-silent-whisper-extrait-de-parfum-50ml-100ml",
    "Senja": "https://officialmykonos.com/products/mykonos-senja-edp-50ml",
    "Royal Ispahan": "https://officialmykonos.com/products/mykonos-royal-ispahan-extrait-de-parfum-50ml-100ml",
    "Reflection": "https://officialmykonos.com/products/mykonos-reflection-extrait-de-parfum-50ml-100ml",
    "Reflection Elixir": "https://officialmykonos.com/products/mykonos-reflection-elixir-extrait-de-parfum-50ml",
}


class MykonosOfficialDetailEvidenceTests(unittest.TestCase):
    def test_selected_identities_use_individual_official_detail_pages(self):
        products = {
            row.get("canonical_name"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Mykonos"
        }
        for name, url in EXPECTED_DETAIL_PAGES.items():
            with self.subTest(product=name):
                row = products.get(name)
                self.assertIsNotNone(row, "missing canonical identity")
                self.assertEqual(row.get("identity_status"), "source_verified_name")
                self.assertEqual(row.get("source_url"), url)
                self.assertEqual(row.get("source_evidence_url"), url)

    def test_variant_evidence_points_to_the_same_official_detail_page(self):
        products = {
            row.get("product_id"): row
            for row in CATALOG.get("products", [])
            if row.get("brand") == "Mykonos"
        }
        for variant in CATALOG.get("variants", []):
            parent = products.get(variant.get("product_id"))
            if parent and parent.get("canonical_name") in EXPECTED_DETAIL_PAGES:
                with self.subTest(variant_id=variant.get("variant_id")):
                    self.assertEqual(
                        variant.get("source_evidence_url"),
                        EXPECTED_DETAIL_PAGES[parent["canonical_name"]],
                    )


if __name__ == "__main__":
    unittest.main()
