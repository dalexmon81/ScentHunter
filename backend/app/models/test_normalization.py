"""Tests for conservative canonical fragrance normalization."""
import unittest

from app.models.normalization import (
    build_identity,
    extract_concentration,
    extract_format_flags,
    extract_size_from_text,
    normalize_brand,
    normalize_fragrance_name,
    normalize_text,
)


class NormalizationTests(unittest.TestCase):
    def test_unicode_case_and_punctuation(self):
        self.assertEqual(normalize_text("  L’Homme Édition! "), "l homme edition")

    def test_exact_curated_brand_aliases(self):
        self.assertEqual(normalize_brand("Christian Dior"), "dior")
        self.assertEqual(normalize_brand("Dior"), "dior")
        self.assertEqual(normalize_brand("Nishane Istanbul"), "nishane")

    def test_brand_substring_is_not_rewritten(self):
        self.assertEqual(normalize_brand("Emporio Armani"), "emporio armani")

    def test_concentration_is_preserved_separately(self):
        self.assertEqual(extract_concentration("Dior Sauvage Eau de Parfum 100 ml"), "edp")
        self.assertEqual(extract_concentration("Dior Sauvage EDT"), "edt")
        self.assertIsNone(extract_concentration("Dior Sauvage"))

    def test_size_only_extracts_explicit_ml(self):
        self.assertEqual(extract_size_from_text("Sauvage EDP 100 ml"), 100)
        self.assertIsNone(extract_size_from_text("Sauvage 3.4 oz"))

    def test_format_flags_do_not_merge_sellable_variants(self):
        self.assertEqual(
            extract_format_flags("Sauvage Eau de Parfum Tester"),
            {"is_tester": True, "is_refill": False, "is_gift_set": False, "is_mini": False},
        )
        regular = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml")
        tester = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml Tester")
        self.assertNotEqual(regular.canonical_key, tester.canonical_key)

    def test_concentration_and_size_make_distinct_keys(self):
        edp_100 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml")
        edt_100 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDT 100 ml")
        edp_60 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 60 ml")
        self.assertEqual(len({edp_100.canonical_key, edt_100.canonical_key, edp_60.canonical_key}), 3)

    def test_fragrance_name_removes_only_known_variant_words(self):
        self.assertEqual(normalize_fragrance_name("Sauvage Eau de Parfum 100 ml"), "sauvage")


if __name__ == "__main__":
    unittest.main()
