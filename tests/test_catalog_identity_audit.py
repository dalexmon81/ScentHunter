"""Tests for the read-only catalog identity audit."""
import copy
import unittest

from backend.scenthunter_next_engine.catalog_identity_audit import build_identity_audit


class CatalogIdentityAuditTests(unittest.TestCase):
    def test_detects_duplicate_identity_and_does_not_mutate_catalog(self):
        source = {
            "products": [
                {"product_id": "p1", "brand_name": "Giorgio Armani", "canonical_name": "Acqua di Giò Profondo", "concentration": "Eau de Parfum", "aliases": ["Profondo"], "canonical_image": "https://example.test/1.jpg"},
                {"product_id": "p2", "brand_name": "Giorgio Armani", "canonical_name": "Acqua di Gio Profondo", "concentration": "Eau de Parfum", "aliases": ["Profondo"], "canonical_image": "https://example.test/2.jpg"},
                {"product_id": "p3", "brand_name": "Giorgio Armani", "canonical_name": "Acqua di Gio", "concentration": "Eau de Toilette", "aliases": [], "canonical_image": ""},
                {"product_id": "p4", "brand_name": "Maison Exemple", "canonical_name": "Image URL Field", "aliases": [], "canonical_image_url": "https://example.test/canonical.jpg"},
            ],
            "variants": [
                {"variant_id": "v1", "product_id": "p1", "size_ml": 75},
                {"variant_id": "v2", "product_id": "p2", "size_ml": 100},
                {"variant_id": "v3", "product_id": "p3", "size_ml": 50},
                {"variant_id": "v3", "product_id": "p3", "size_ml": 50},
            ],
        }
        before = copy.deepcopy(source)
        report = build_identity_audit(source)
        self.assertEqual(report["duplicate_normalized_brand_name"]["count"], 1)
        self.assertEqual(report["duplicate_normalized_brand_name_concentration"]["count"], 1)
        self.assertEqual(report["shared_product_aliases"]["count"], 1)
        self.assertEqual(report["duplicate_variant_ids"]["count"], 1)
        self.assertEqual(report["duplicate_sizes_within_product"]["count"], 1)
        self.assertEqual(report["products_missing_image"]["count"], 1)
        self.assertEqual(source, before)
        self.assertTrue(report["read_only"])
        self.assertFalse(report["catalog_mutated"])

    def test_distinct_concentrations_are_reviewed_not_merged(self):
        source = {
            "products": [
                {"product_id": "edt", "brand_name": "Guerlain", "canonical_name": "Shalimar", "concentration": "Eau de Toilette"},
                {"product_id": "edp", "brand_name": "Guerlain", "canonical_name": "Shalimar", "concentration": "Eau de Parfum"},
            ],
            "variants": [
                {"variant_id": "v1", "product_id": "edt", "size_ml": 50},
                {"variant_id": "v2", "product_id": "edp", "size_ml": 50},
            ],
        }
        report = build_identity_audit(source)
        self.assertEqual(report["duplicate_normalized_brand_name"]["count"], 1)
        self.assertEqual(report["duplicate_normalized_brand_name_concentration"]["count"], 0)
        self.assertIn("No product", report["policy"])

    def test_separates_brand_only_aliases_from_product_alias_collisions(self):
        source = {
            "products": [
                {"product_id": "p1", "brand_name": "Giorgio Armani", "canonical_name": "Acqua di Gio", "aliases": ["Giorgio Armani", "Acqua di Gio EDT"]},
                {"product_id": "p2", "brand_name": "Giorgio Armani", "canonical_name": "My Way", "aliases": ["Giorgio Armani", "My Way Intense"]},
                {"product_id": "p3", "brand_name": "Maison Exemple", "canonical_name": "Example", "aliases": ["Shared Product Alias"]},
                {"product_id": "p4", "brand_name": "Other Exemple", "canonical_name": "Other", "aliases": ["Shared Product Alias"]},
            ],
            "variants": [],
        }
        report = build_identity_audit(source)
        self.assertEqual(report["shared_brand_only_aliases"]["count"], 1)
        self.assertEqual(report["shared_brand_only_aliases"]["items"][0]["alias"], "giorgio armani")
        self.assertEqual(report["shared_product_aliases"]["count"], 1)
        self.assertEqual(report["shared_product_aliases"]["items"][0]["alias"], "shared product alias")

    def test_flags_expanded_brand_alias_as_candidate_without_hiding_collision(self):
        source = {
            "products": [
                {"product_id": "p1", "brand_name": "Armani", "canonical_name": "Acqua di Gio", "aliases": ["Giorgio Armani", "Giorgio Armani Acqua di Gio"]},
                {"product_id": "p2", "brand_name": "Armani", "canonical_name": "My Way", "aliases": ["Giorgio Armani"]},
                {"product_id": "p3", "brand_name": "Dior", "canonical_name": "Sauvage", "aliases": ["Christian Dior"]},
                {"product_id": "p4", "brand_name": "Dior", "canonical_name": "J'adore", "aliases": ["Christian Dior"]},
                {"product_id": "p5", "brand_name": "Guerlain", "canonical_name": "Shalimar", "aliases": ["Guerlain Shalimar"]},
                {"product_id": "p6", "brand_name": "Guerlain", "canonical_name": "Mitsouko", "aliases": ["Guerlain Mitsouko"]},
            ],
            "variants": [],
        }
        report = build_identity_audit(source)
        candidates = {item["alias"] for item in report["possible_brand_aliases_for_review"]["items"]}
        self.assertEqual(candidates, {"giorgio armani", "christian dior"})
        # Candidates remain visible as collisions; this is not a confirmed correction.
        self.assertEqual(report["shared_product_aliases"]["count"], 3)
        self.assertTrue(all(item["classification"] == "possible_brand_alias_not_confirmed"
                            for item in report["possible_brand_aliases_for_review"]["items"]))

    def test_requires_product_and_variant_arrays(self):
        with self.assertRaises(ValueError):
            build_identity_audit({"products": []})


if __name__ == "__main__":
    unittest.main()
