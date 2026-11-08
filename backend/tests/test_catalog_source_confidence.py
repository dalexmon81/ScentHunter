"""Regression checks for catalog source provenance and confidence labels."""
import json
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
CATALOG = json.loads((BACKEND / "product_catalog.json").read_text(encoding="utf-8"))


class CatalogSourceConfidenceTests(unittest.TestCase):
    def test_every_identity_has_a_source_reference(self):
        for product in CATALOG["products"]:
            with self.subTest(product=product.get("product_id")):
                self.assertTrue(product.get("source_url") or product.get("source_evidence_url"))

    def test_every_identity_has_an_explicit_evidence_status(self):
        allowed = {"source_verified_name", "source_listed_name"}
        for product in CATALOG["products"]:
            with self.subTest(product=product.get("product_id")):
                self.assertIn(product.get("identity_status"), allowed)

    def test_collection_listed_names_are_not_misrepresented_as_verified(self):
        listed = [p for p in CATALOG["products"] if p.get("identity_status") == "source_listed_name"]
        self.assertGreater(len(listed), 0)
        self.assertTrue(all(p.get("source_url") or p.get("source_evidence_url") for p in listed))


if __name__ == "__main__":
    unittest.main()
