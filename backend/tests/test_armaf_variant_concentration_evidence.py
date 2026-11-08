"""Evidence-backed concentration checks for selected Armaf Club de Nuit variants."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))

EXPECTED = {
    "Club de Nuit Untold": {
        "source": "https://armaf.com/products/armaf-club-de-nuit-untold",
        "sizes": {10, 30, 105, 200},
    },
    "Club de Nuit Sillage": {
        "source": "https://armaf.com/products/armaf-club-de-nuit-silage-men",
        "sizes": {10, 30, 105, 250},
    },
    "Club de Nuit Woman": {
        "source": "https://armaf.com/products/club-de-nuit-w",
        "sizes": {10, 30, 105, 200, 250},
    },
    "Club de Nuit Urban Man Elixir": {
        "source": "https://armaf.com/products/club-de-nuit-urban-elixir-100ml",
        "sizes": {10, 30, 105, 250},
    },
    "Club de Nuit Iconic": {
        "source": "https://armaf.com/products/club-de-nuit-blue-iconic-200ml",
        "sizes": {10, 30, 105, 200},
    },
}


class ArmafVariantConcentrationEvidenceTests(unittest.TestCase):
    def test_officially_documented_club_de_nuit_variants_are_edp(self):
        products = {
            row.get("product_id"): row
            for row in CATALOG.get("products", [])
            if (row.get("brand_name") or row.get("brand")) == "Armaf"
        }
        variants = CATALOG.get("variants", [])

        for name, evidence in EXPECTED.items():
            matching_products = [
                row for row in products.values()
                if (row.get("canonical_name") or row.get("name")) == name
            ]
            self.assertEqual(len(matching_products), 1, name)
            product = matching_products[0]
            self.assertEqual(product.get("source_url"), evidence["source"], name)

            matching_variants = [
                row for row in variants
                if row.get("product_id") == product.get("product_id")
            ]
            self.assertEqual(
                {row.get("size_ml") for row in matching_variants},
                evidence["sizes"],
                name,
            )
            for variant in matching_variants:
                self.assertEqual(variant.get("concentration"), "Eau de Parfum")
                self.assertEqual(variant.get("source_url"), evidence["source"])


if __name__ == "__main__":
    unittest.main()
