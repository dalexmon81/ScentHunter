import unittest
import tempfile
from pathlib import Path

from backend.scripts.build_notino_match_candidates import (
    build_catalog_index, score_row, extract_concentration, parse_size,
    iter_perfume_rows,
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
        self.assertEqual(parse_size("3.4 fl oz"), 100.55)
        self.assertEqual(parse_size("1,7 fl. oz."), 50.28)
        self.assertIsNone(parse_size("3.4 oz"))
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


    def test_known_retailer_brand_aliases_map_to_canonical_brands(self):
        catalog = {
            "products": [{
                "product_id": "P-R",
                "brand_name": "Paco Rabanne",
                "canonical_name": "1 Million",
                "family_name": "1 Million",
                "concentration": "Eau de Toilette",
                "aliases": ["1 Million"],
            }],
            "variants": [{
                "variant_id": "V-R",
                "product_id": "P-R",
                "size_ml": 100,
                "gtins": [],
                "aliases": [],
            }],
        }
        index = build_catalog_index(catalog)
        row = {
            "id": "RABANNE-1",
            "brand": "Rabanne",
            "title": "Rabanne 1 Million Eau de Toilette 100 ml",
            "size": "100 ml",
        }
        candidates = score_row(row, index)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["canonical_product_id"], "P-R")

    def test_exact_gtin_is_explicitly_marked_but_still_requires_review(self):
        catalog = {
            "products": [{
                "product_id": "P-G",
                "brand_name": "Dior",
                "canonical_name": "Sauvage",
                "family_name": "Sauvage",
                "concentration": "Eau de Parfum",
                "aliases": ["Sauvage"],
            }],
            "variants": [{
                "variant_id": "V-G",
                "product_id": "P-G",
                "size_ml": 100,
                "gtins": ["8011003809202"],
                "aliases": [],
            }],
        }
        index = build_catalog_index(catalog)
        row = {
            "id": "SKU-GTIN",
            "gtin": "8011003809202",
            "brand": "Dior",
            "title": "Dior Sauvage Eau de Parfum 100 ml",
            "size": "100 ml",
        }
        candidate = score_row(row, index)[0]
        self.assertTrue(candidate["gtin_match"])
        self.assertEqual(candidate["confidence_band"], "review_high")
        self.assertEqual(candidate["review_status"], "needs_human_review")


    def test_invalid_feed_gtin_cannot_create_exact_gtin_match(self):
        catalog = {
            "products": [{
                "product_id": "P-GTIN-INVALID",
                "brand_name": "Dior",
                "canonical_name": "Sauvage",
                "family_name": "Sauvage",
                "concentration": "Eau de Parfum",
                "aliases": ["Sauvage"],
            }],
            "variants": [{
                "variant_id": "V-GTIN-INVALID",
                "product_id": "P-GTIN-INVALID",
                "size_ml": 100,
                "gtins": ["1234567890123"],
                "aliases": [],
            }],
        }
        index = build_catalog_index(catalog)
        candidate = score_row({
            "id": "INVALID-GTIN",
            "gtin": "1234567890123",
            "brand": "Dior",
            "title": "Dior Sauvage Eau de Parfum 100 ml",
            "size": "100 ml",
        }, index)[0]
        self.assertFalse(candidate["gtin_match"])

    def test_gender_conflict_cannot_be_high_confidence(self):
        catalog = {
            "products": [{
                "product_id": "P-W",
                "brand_name": "Burberry",
                "canonical_name": "London for Men",
                "family_name": "London for Men",
                "concentration": "Eau de Parfum",
                "aliases": [],
            }],
            "variants": [{
                "variant_id": "V-W",
                "product_id": "P-W",
                "size_ml": 100,
                "gtins": [],
                "aliases": [],
            }],
        }
        index = build_catalog_index(catalog)
        row = {
            "id": "LONDON-WOMEN",
            "brand": "Burberry",
            "title": "Burberry London for Women Eau de Parfum 100 ml",
            "size": "100 ml",
        }
        candidate = score_row(row, index)[0]
        self.assertTrue(candidate["gender_conflict"])
        self.assertEqual(candidate["confidence_band"], "low")


    def test_gender_extraction_detects_men_and_women_terms(self):
        from backend.scripts.build_notino_match_candidates import extract_gender
        self.assertEqual(extract_gender("Burberry London for Women"), "women")
        self.assertEqual(extract_gender("Burberry London for Men"), "men")
        self.assertEqual(extract_gender("pour homme"), "men")
        self.assertEqual(extract_gender("pour femme"), "women")

    def test_wrong_concentration_cannot_be_high_confidence(self):
        row = {
            "id": "SKU-EDT",
            "brand": "Dior",
            "title": "Dior Sauvage Eau de Toilette 100 ml",
            "size": "100 ml",
        }
        candidates = score_row(row, self.index)
        self.assertTrue(candidates)
        self.assertFalse(candidates[0]["concentration_match"])
        self.assertEqual(candidates[0]["confidence_band"], "low")

    def test_size_is_read_from_title_when_feed_size_field_is_empty(self):
        row = {
            "id": "SKU-TITLE-SIZE",
            "brand": "Dior",
            "title": "Dior Sauvage Eau de Parfum 50 ml",
            "size": "",
        }
        candidates = score_row(row, self.index)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["feed_size_ml"], 50.0)
        self.assertFalse(candidates[0]["size_match"])
        self.assertEqual(candidates[0]["confidence_band"], "low")


    def test_intense_concentrations_remain_distinct(self):
        self.assertEqual(
            extract_concentration("Dior Homme Eau de Toilette Intense"),
            "EDT_INTENSE",
        )
        self.assertEqual(
            extract_concentration("Dior Homme Pure Parfum"),
            "PARFUM",
        )

    def test_variant_concentration_is_used_when_parent_is_unspecified(self):
        catalog = {
            "products": [{
                "product_id": "P-V",
                "brand_name": "Dior",
                "canonical_name": "Sauvage",
                "family_name": "Sauvage",
                "concentration": "",
                "aliases": [],
            }],
            "variants": [{
                "variant_id": "V-V",
                "product_id": "P-V",
                "size_ml": 100,
                "concentration": "Eau de Parfum",
                "gtins": [],
                "aliases": [],
            }],
        }
        index = build_catalog_index(catalog)
        self.assertEqual(index[0]["concentration"], "EDP")

    def test_candidate_feed_scope_excludes_gift_sets_and_non_perfume_categories(self):
        xml = """<?xml version="1.0"?>
        <feed>
          <entry>
            <id>CORE</id><google_product_category>479</google_product_category>
            <product_type>Parfémy &gt; Pánské parfémy &gt; Toaletní vody</product_type>
          </entry>
          <entry>
            <id>GIFT</id><google_product_category>479</google_product_category>
            <product_type>Parfémy &gt; Dárkové sady</product_type>
          </entry>
          <entry>
            <id>OTHER</id><google_product_category>123</google_product_category>
            <product_type>Toaletní vody</product_type>
          </entry>
        </feed>"""
        with tempfile.TemporaryDirectory() as directory:
            feed = Path(directory) / "feed.xml"
            feed.write_text(xml, encoding="utf-8")
            rows = list(iter_perfume_rows(feed))
        self.assertEqual([row["id"] for row in rows], ["CORE"])

    def test_product_without_variants_is_indexed_as_product_only_review_candidate(self):
        catalog = {
            "products": [{
                "product_id": "P-ONLY",
                "brand_name": "Dior",
                "canonical_name": "Homme Intense",
                "family_name": "Homme Intense",
                "concentration": "Eau de Parfum",
                "aliases": ["Dior Homme Intense"],
            }],
            "variants": [],
        }
        index = build_catalog_index(catalog)
        self.assertEqual(len(index), 1)
        self.assertEqual(index[0]["candidate_scope"], "product_only")
        candidates = score_row({
            "id": "SKU-PRODUCT-ONLY",
            "brand": "Dior",
            "title": "Dior Homme Intense Eau de Parfum",
            "size": "",
        }, index)
        self.assertTrue(candidates)
        self.assertEqual(candidates[0]["canonical_product_id"], "P-ONLY")
        self.assertEqual(candidates[0]["canonical_variant_id"], "")
        self.assertEqual(candidates[0]["candidate_scope"], "product_only")
        self.assertNotEqual(candidates[0]["confidence_band"], "review_high")

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
