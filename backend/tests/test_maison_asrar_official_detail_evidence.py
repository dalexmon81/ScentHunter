"""Guard official individual product-page evidence for Maison Asrar."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Ameer": "https://maisonasrar.com/products/ameer",
    "Aseel": "https://maisonasrar.com/products/aseel",
    "1963": "https://maisonasrar.com/products/1963-eau-de-perfum-100ml",
}


class MaisonAsrarOfficialDetailEvidenceTests(unittest.TestCase):
    def test_selected_products_use_their_official_detail_pages(self):
        rows = [
            row for row in CATALOG.get("products", [])
            if (row.get("brand_name") or row.get("brand") or "").strip() == "Maison Asrar"
        ]
        for name, expected_url in EXPECTED.items():
            matches = [
                row for row in rows
                if (row.get("canonical_name") or row.get("name")) == name
            ]
            self.assertEqual(len(matches), 1, f"Expected one canonical identity for {name}")
            self.assertEqual(matches[0].get("source_url"), expected_url)
            self.assertEqual(matches[0].get("identity_status"), "source_verified_name")


if __name__ == "__main__":
    unittest.main()
