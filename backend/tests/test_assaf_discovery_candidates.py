"""Checks discovery-only Assaf candidate records sourced from an independent guide."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "product_catalog.json").read_text(encoding="utf-8"))
REGISTRY = json.loads((ROOT / "family_registry.json").read_text(encoding="utf-8"))


class AssafDiscoveryCandidateTests(unittest.TestCase):
    def test_candidates_have_explicit_unofficial_provenance(self):
        candidates = [
            p for p in CATALOG["products"]
            if p.get("source_evidence_type") == "independent_reseller_guide"
        ]
        self.assertEqual(len(candidates), 119)
        self.assertTrue(all(p.get("review_required") is True for p in candidates))
        self.assertTrue(all(p.get("identity_status") == "source_listed_name" for p in candidates))
        self.assertTrue(all(p.get("source_url") == "https://assafperfumes.eu/perfumes/" for p in candidates))

    def test_candidates_do_not_invent_variant_or_commercial_data(self):
        candidates = [
            p for p in CATALOG["products"]
            if p.get("source_evidence_type") == "independent_reseller_guide"
        ]
        forbidden = {
            "price", "stock", "availability", "gtin", "ean", "sku",
            "size_ml", "formats_ml", "concentration", "shipping_cost",
        }
        for product in candidates:
            self.assertFalse(forbidden.intersection(product.keys()), product["canonical_name"])

    def test_family_registry_contains_all_candidates(self):
        family = next(f for f in REGISTRY["families"] if f["family_id"] == "assaf_catalog")
        candidate_names = {
            p["canonical_name"] for p in CATALOG["products"]
            if p.get("source_evidence_type") == "independent_reseller_guide"
        }
        registry_names = {p["canonical_name"] for p in family["products"]}
        self.assertTrue(candidate_names.issubset(registry_names))


if __name__ == "__main__":
    unittest.main()
