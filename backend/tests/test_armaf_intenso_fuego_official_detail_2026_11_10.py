"""Regression coverage for Armaf Club de Nuit Intenso Fuego official detail data."""

import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((BACKEND / "family_registry.json").read_text(encoding="utf-8"))

PRODUCT_ID = "SH-ARMAF-4c83dfcd"
SOURCE_URL = "https://armaf.com/products/club-de-nuit-intenso-fuego"
VARIANT_ID = "SHV-SH-ARMAF-4c83dfcd-105-EDP"


class ArmafIntensoFuegoOfficialDetailTests(unittest.TestCase):
    def test_existing_canonical_product_is_upgraded_with_detail_evidence(self):
        rows = [p for p in CATALOG["products"] if p.get("product_id") == PRODUCT_ID]
        self.assertEqual(len(rows), 1)
        product = rows[0]
        self.assertEqual(product["canonical_name"], "Club de Nuit Intenso Fuego")
        self.assertEqual(product["identity_status"], "source_verified_name")
        self.assertEqual(product["source_url"], SOURCE_URL)
        self.assertEqual(product["source_product_url"], SOURCE_URL)
        self.assertEqual(product["source_evidence_url"], SOURCE_URL)
        self.assertEqual(product["concentration"], "Eau de Parfum")
        self.assertEqual(product["gender"], "Men")
        self.assertEqual(product["formats_ml"], [105])

    def test_official_105ml_variant_is_unique_and_linked(self):
        rows = [v for v in CATALOG["variants"] if v.get("variant_id") == VARIANT_ID]
        self.assertEqual(len(rows), 1)
        variant = rows[0]
        self.assertEqual(variant["product_id"], PRODUCT_ID)
        self.assertEqual(variant["size_ml"], 105)
        self.assertEqual(variant["concentration"], "Eau de Parfum")
        self.assertEqual(variant["source_url"], SOURCE_URL)
        self.assertEqual(variant["source_evidence_url"], SOURCE_URL)
        self.assertEqual(
            len([v for v in CATALOG["variants"] if v.get("product_id") == PRODUCT_ID]),
            1,
        )

    def test_family_registry_records_the_verified_format(self):
        family = next(f for f in REGISTRY["families"] if f.get("brand") == "Armaf")
        entry = next(p for p in family["products"] if p.get("canonical_name") == "Club de Nuit Intenso Fuego")
        self.assertEqual(entry.get("formats_ml"), [105])


if __name__ == "__main__":
    unittest.main()
