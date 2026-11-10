import unittest

from backend.scripts.build_notino_match_candidates import (
    build_catalog_index, score_row, extract_concentration, parse_size,
)


class NotinoCandidateMatchingTests(unittest.TestCase):
    def setUp(self):
        catalog = {
            "products": [{
                "product_id": "P-1",
                "brand_name": "Dior",
                "canonical_name": "Sauvage",
                "family_name": "Sauvage",
                "concentration": "Eau de Parfum",
                "aliases": ["Dior Sauvage EDP"],
            }],
            "variants": [{
                "variant_id": "V-1",
                "product_id": "P-1",
                "size_ml": 100,
                "gtins": [],
                "aliases": [],
            }],
        }
        self.index = build_catalog_index(catalog)

    def test_extracts_size_and_concentration(self):
        self.assertEqual(parse_size("100 ml"), 100.0)
        self.assertEqual(extract_concentration("Dior Sauvage Eau de Parfum 100 ml"), "EDP")

    def test_exact_brand_name_size_and_concentration_is_review_only(self):
        row = {
            "id": "SKU-1",
            "gtin": "1234567890123",
            "brand": "Dior",
            "title": "Dior Sauvage Eau de Parfum 100 ml",
            "size": "100 ml",
        }
        candidates = score_row(row, self.index)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["canonical_variant_id"], "V-1")
        self.assertEqual(candidates[0]["confidence_band"], "review_high")
        self.assertEqual(candidates[0]["review_status"], "needs_human_review")

    def test_brand_mismatch_never_generates_candidate(self):
        row = {
            "id": "SKU-2",
            "brand": "Chanel",
            "title": "Sauvage Eau de Parfum 100 ml",
            "size": "100 ml",
        }
        self.assertEqual(score_row(row, self.index), [])

    def test_size_conflict_cannot_be_high_confidence(self):
        row = {
            "id": "SKU-3",
            "brand": "Dior",
            "title": "Dior Sauvage Eau de Parfum 50 ml",
            "size": "50 ml",
        }
        candidates = score_row(row, self.index)
        self.assertTrue(candidates)
        self.assertNotEqual(candidates[0]["confidence_band"], "review_high")
        self.assertFalse(candidates[0]["size_match"])


if __name__ == "__main__":
    unittest.main()
