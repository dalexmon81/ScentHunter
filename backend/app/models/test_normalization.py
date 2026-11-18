"""Unit tests for conservative canonical identity normalization."""
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

    def test_substring_brand_alias_is_not_used(self):
        self.assertEqual(normalize_brand("Emporio Armani"), "emporio armani")

    def test_concentration_is_explicit(self):
        self.assertEqual(extract_concentration("Sauvage Eau de Parfum 100 ml"), "edp")
        self.assertEqual(extract_concentration("Sauvage EDT"), "edt")
        self.assertIsNone(extract_concentration("Sauvage"))

    def test_size_extraction_only_accepts_ml(self):
        self.assertEqual(extract_size_from_text("Sauvage EDP 100 ml"), 100)
        self.assertIsNone(extract_size_from_text("Sauvage 3.4 oz"))

    def test_formats_are_separate_identity_attributes(self):
        flags = extract_format_flags("Sauvage Eau de Parfum Tester")
        self.assertTrue(flags["is_tester"])
        self.assertFalse(flags["is_refill"])
        regular = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml")
        tester = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml Tester")
        self.assertNotEqual(regular.canonical_key, tester.canonical_key)

    def test_concentration_and_size_create_distinct_keys(self):
        edp_100 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 100 ml")
        edt_100 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDT 100 ml")
        edp_60 = build_identity(brand="Dior", fragrance_name="Sauvage", title="Sauvage EDP 60 ml")
        self.assertEqual(len({edp_100.canonical_key, edt_100.canonical_key, edp_60.canonical_key}), 3)

    def test_name_normalization_keeps_model_numbers(self):
        self.assertEqual(normalize_fragrance_name("No. 5 Eau de Parfum 100 ml"), "no 5")
        self.assertEqual(normalize_fragrance_name("Sauvage Eau de Parfum 100 ml"), "sauvage")


if __name__ == "__main__":
    unittest.main()
