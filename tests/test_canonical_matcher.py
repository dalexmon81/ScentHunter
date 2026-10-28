"""Regression tests for conservative canonical matching and catalog aliases."""
import json
import tempfile
import unittest
from pathlib import Path

from backend.scenthunter_next_engine.catalog_repository import CatalogRepository
from backend.scenthunter_next_engine.models import MatchStatus, RetailerOffer
from backend.scenthunter_next_engine.canonical_matcher import (
    CanonicalMatcher,
    normalize_identity_text,
)


class CanonicalMatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".json", delete=False
        )
        json.dump(
            {
                "products": [
                    {
                        "product_id": "P-ONE",
                        "brand_name": "Maison Exemple",
                        "canonical_name": "Bois Clair",
                        "aliases": [
                            "Maison Exemple Bois Clair",
                            "Bois Clair Eau de Parfum",
                        ],
                    },
                    {
                        "product_id": "P-TWO",
                        "brand_name": "Maison Exemple",
                        "canonical_name": "Bois Clair",
                        "aliases": [],
                    },
                    {
                        "product_id": "P-MULTI",
                        "brand_name": "Autre Maison",
                        "canonical_name": "Nuit Douce",
                        "aliases": ["Nuit Douce"],
                    },
                    {
                        "product_id": "P-NOVAR",
                        "brand_name": "Sans Format",
                        "canonical_name": "Sans Variante",
                    },
                    {
                        "product_id": "P-UNIQUE",
                        "brand_name": "Maison Unique",
                        "canonical_name": "Aube",
                        "aliases": ["Aube Eau de Parfum"],
                    },
                    {
                        "product_id": "P-LIQUID",
                        "brand_name": "French Avenue",
                        "canonical_name": "Liquid Brun Limited Edition",
                        "aliases": [
                            "French Avenue Liquid Brun Limited Edition",
                            "Liquid Brun Limited Edition 150ml",
                            "Liquid Brun Limited Edition Extrait de Parfum",
                        ],
                    },
                    {
                        "product_id": "P-LIQUID-BASE",
                        "brand_name": "French Avenue",
                        "canonical_name": "Liquid Brun",
                        "aliases": ["Liquid Brun 100 ML"],
                    },
                    {
                        "product_id": "P-CODE",
                        "brand_name": "Armani",
                        "canonical_name": "Code",
                        "aliases": [],
                    },
                    {
                        "product_id": "P-CODE-PARFUM",
                        "brand_name": "Armani",
                        "canonical_name": "Code Parfum",
                        "aliases": [],
                    },
                    {
                        "product_id": "P-HABIT-EDP",
                        "brand_name": "Guerlain",
                        "canonical_name": "Habit Rouge",
                        "concentration": "Eau de Parfum",
                        "aliases": [],
                    },
                    {
                        "product_id": "P-HABIT-EDT",
                        "brand_name": "Guerlain",
                        "canonical_name": "Habit Rouge",
                        "concentration": "Eau de Toilette",
                        "aliases": [],
                    },
                    {
                        "product_id": "P-HABIT-EDP-DUP",
                        "brand_name": "Guerlain",
                        "canonical_name": "Habit Rouge",
                        "concentration": "Eau de Parfum",
                        "aliases": [],
                    },
                ],
                "variants": [
                    {"variant_id": "V-100", "product_id": "P-ONE", "size_ml": 100},
                    {"variant_id": "V-50", "product_id": "P-TWO", "size_ml": 50},
                    {
                        "variant_id": "V-N-30",
                        "product_id": "P-MULTI",
                        "size_ml": 30,
                        "aliases": ["Nuit Douce 30 ml"],
                    },
                    {
                        "variant_id": "V-N-75",
                        "product_id": "P-MULTI",
                        "size_ml": 75,
                        "aliases": [
                            "Nuit Douce 75 ml",
                            "Nuit Douce 30 ml",
                        ],
                    },
                    {
                        "variant_id": "V-AUBE-100",
                        "product_id": "P-UNIQUE",
                        "size_ml": 100,
                    },
                    {
                        "variant_id": "V-LIQUID-150",
                        "product_id": "P-LIQUID",
                        "size_ml": 150,
                        "aliases": [
                            "Liquid Brun Limited Edition Extrait de Parfum",
                            "Liquid Brun Limited Edition 150ml",
                        ],
                    },
                    {
                        "variant_id": "V-LIQUID-100",
                        "product_id": "P-LIQUID-BASE",
                        "size_ml": 100,
                        "aliases": ["Liquid Brun 100 ML"],
                    },
                    {"variant_id": "V-CODE-100", "product_id": "P-CODE", "size_ml": 100},
                    {"variant_id": "V-CODE-PARFUM-100", "product_id": "P-CODE-PARFUM", "size_ml": 100},
                    {"variant_id": "V-HABIT-EDP-50", "product_id": "P-HABIT-EDP", "size_ml": 50},
                    {"variant_id": "V-HABIT-EDT-50", "product_id": "P-HABIT-EDT", "size_ml": 50},
                    {"variant_id": "V-HABIT-EDP-DUP-50", "product_id": "P-HABIT-EDP-DUP", "size_ml": 50},
                ],
            },
            self.tmp,
        )
        self.tmp.flush()
        self.addCleanup(lambda: Path(self.tmp.name).unlink(missing_ok=True))
        # Give this fixture a unique sibling directory: CanonicalMatcher
        # resolves the reviewed GTIN sidecar relative to the temporary catalog.
        self.fixture_dir = Path(
            tempfile.mkdtemp(prefix="scenthunter-test-")
        )
        self.catalog_path = self.fixture_dir / "product_catalog.json"
        self.tmp.seek(0)
        self.catalog_path.write_text(
            self.tmp.read(),
            encoding="utf-8",
        )
        self.registry_path = self.fixture_dir / "scenthunter_next_engine" / "verified_gtin_variant_map.json"
        self.registry_path.parent.mkdir()
        self.registry_path.write_text(
            json.dumps({
                "schema_version": 1,
                "records": [{
                    "gtin": "6298042001831",
                    "gtin_type": "GTIN-13",
                    "status": "verified",
                    "product_id": "P-LIQUID",
                    "variant_id": "V-LIQUID-150",
                    "size_ml": 150,
                    "concentration": "Extrait de Parfum",
                    "refill": False,
                    "source_urls": [
                        "https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
                    ],
                }],
            }),
            encoding="utf-8",
        )
        self.addCleanup(lambda: __import__("shutil").rmtree(self.fixture_dir, ignore_errors=True))
        self.matcher = CanonicalMatcher(
            CatalogRepository.from_file(self.catalog_path)
        )

    def offer(self, name, brand=None, size=None):
        return RetailerOffer(
            retailer="Test Shop",
            raw_name=name,
            brand_raw=brand,
            size_ml=size,
        )

    def test_normalizes_accents_and_punctuation(self):
        self.assertEqual(
            normalize_identity_text("Été & Nuit!"),
            "ete and nuit",
        )

    def test_duplicate_canonical_names_remain_ambiguous(self):
        result = self.matcher.match(
            self.offer("Bois Clair", "Maison Exemple", 100)
        )
        self.assertEqual(result.status, MatchStatus.AMBIGUOUS)
        self.assertEqual(
            set(result.candidate_product_ids),
            {"P-ONE", "P-TWO"},
        )

    def test_unique_name_brand_and_size_match_real_ids(self):
        result = self.matcher.match(
            self.offer("Aube", "Maison Unique", 100)
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-UNIQUE")
        self.assertEqual(result.canonical_variant_id, "V-AUBE-100")

    def test_generic_concentration_suffix_is_tolerated(self):
        result = self.matcher.match(
            self.offer("Aube Eau de Parfum", "Maison Unique", 100)
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_variant_id, "V-AUBE-100")

    def test_wrong_brand_never_matches_product(self):
        result = self.matcher.match(
            self.offer("Aube", "Brand Sbagliato", 100)
        )
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(
            result.reason,
            "no_exact_canonical_name_and_brand_match",
        )

    def test_name_match_without_brand_is_ambiguous_when_multiple_products_exist(self):
        result = self.matcher.match(self.offer("Bois Clair", size=100))
        self.assertEqual(result.status, MatchStatus.AMBIGUOUS)

    def test_multi_variant_product_without_size_stays_unresolved(self):
        result = self.matcher.match(
            self.offer("Nuit Douce", "Autre Maison")
        )
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(
            result.reason,
            "format_missing_for_multi_variant_product",
        )

    def test_explicit_size_without_canonical_variant_stays_unresolved(self):
        result = self.matcher.match(
            self.offer("Nuit Douce", "Autre Maison", 100)
        )
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(
            result.reason,
            "explicit_size_has_no_canonical_variant",
        )

    def test_no_fuzzy_name_match(self):
        result = self.matcher.match(
            self.offer("Bois Clair Extra", "Maison Exemple", 100)
        )
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)

    def test_product_without_variants_stays_unresolved(self):
        result = self.matcher.match(
            self.offer("Sans Variante", "Sans Format")
        )
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(
            result.reason,
            "canonical_product_has_no_declared_variants",
        )

    def test_product_alias_shared_by_products_remains_ambiguous(self):
        result = self.matcher.match(
            self.offer("Bois Clair Eau de Parfum", "Maison Exemple", 100)
        )
        self.assertEqual(result.status, MatchStatus.AMBIGUOUS)

    def test_variant_alias_resolves_format_when_size_field_missing(self):
        result = self.matcher.match(
            self.offer("Nuit Douce 75 ml", "Autre Maison")
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_variant_id, "V-N-75")

    def test_shared_variant_alias_without_size_stays_unresolved(self):
        result = self.matcher.match(
            self.offer("Nuit Douce 30 ml", "Autre Maison")
        )
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(
            result.reason,
            "variant_alias_does_not_identify_unique_format",
        )

    def test_explicit_size_conflicting_with_variant_alias_fails_closed(self):
        result = self.matcher.match(
            self.offer("Nuit Douce 75 ml", "Autre Maison", 30)
        )
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(
            result.reason,
            "matched_variant_alias_conflicts_with_explicit_size",
        )

    def test_liquid_brun_limited_edition_alias_matches_canonical_variant(self):
        result = self.matcher.match(
            self.offer(
                "Liquid Brun Limited Edition Extrait De Parfum",
                "FRENCH AVENUE",
                150,
            )
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-LIQUID")
        self.assertEqual(result.canonical_variant_id, "V-LIQUID-150")

    def test_liquid_brun_100_ml_alias_matches_canonical_variant(self):
        result = self.matcher.match(
            self.offer("Liquid Brun 100 ML", "FRENCH AVENUE", 100)
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-LIQUID-BASE")
        self.assertEqual(result.canonical_variant_id, "V-LIQUID-100")

    def test_strict_full_title_wins_over_suffix_stripped_collision(self):
        result = self.matcher.match(
            self.offer("Code Parfum", "Armani", 100)
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-CODE-PARFUM")
        self.assertEqual(result.canonical_variant_id, "V-CODE-PARFUM-100")

    def test_short_title_prefers_exact_title_over_suffix_fallback_collision(self):
        result = self.matcher.match(
            self.offer("Code", "Armani", 100)
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-CODE")
        self.assertEqual(result.canonical_variant_id, "V-CODE-100")

    def test_explicit_concentration_disambiguates_distinct_catalog_products(self):
        result = self.matcher.match(
            self.offer("Habit Rouge Eau de Toilette", "Guerlain", 50)
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-HABIT-EDT")
        self.assertEqual(result.canonical_variant_id, "V-HABIT-EDT-50")

    def test_missing_concentration_does_not_guess_between_distinct_products(self):
        result = self.matcher.match(
            self.offer("Habit Rouge", "Guerlain", 50)
        )
        self.assertEqual(result.status, MatchStatus.AMBIGUOUS)
        self.assertEqual(
            set(result.candidate_product_ids),
            {"P-HABIT-EDP", "P-HABIT-EDT", "P-HABIT-EDP-DUP"},
        )

    def test_duplicate_products_with_same_concentration_remain_ambiguous(self):
        result = self.matcher.match(
            self.offer("Habit Rouge Eau de Parfum", "Guerlain", 50)
        )
        self.assertEqual(result.status, MatchStatus.AMBIGUOUS)
        self.assertEqual(
            set(result.candidate_product_ids),
            {"P-HABIT-EDP", "P-HABIT-EDP-DUP"},
        )


    def test_deloox_verified_gtin_maps_limited_edition_to_real_150ml_variant(self):
        result = self.matcher.match(
            RetailerOffer(
                retailer="deloox",
                raw_name="French Avenue Liquid Brun Extrait de Parfum Limited edition 150 ml",
                brand_raw="French Avenue",
                size_ml=150,
                price=None,
                availability="out_of_stock",
                product_url="https://www.deloox.be/produit/1385920/french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html",
                raw_payload={"gtin13": "6298042001831", "sku": "1385920"},
            )
        )
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-LIQUID")
        self.assertEqual(result.canonical_variant_id, "V-LIQUID-150")
        self.assertEqual(result.offer.availability, "out_of_stock")
        self.assertIsNone(result.offer.price)

    def test_liquid_brun_standard_100ml_stays_separate_from_limited_edition(self):
        limited = self.matcher.match(
            RetailerOffer(
                retailer="deloox",
                raw_name="French Avenue Liquid Brun Extrait de Parfum Limited edition 150 ml",
                brand_raw="French Avenue",
                size_ml=150,
                price=None,
                availability="out_of_stock",
                raw_payload={"gtin13": "6298042001831"},
            )
        )
        standard = self.matcher.match(
            RetailerOffer(
                retailer="another-shop",
                raw_name="Liquid Brun",
                brand_raw="French Avenue",
                size_ml=100,
            )
        )
        self.assertEqual(limited.status, MatchStatus.MATCHED)
        self.assertEqual(standard.status, MatchStatus.MATCHED)
        self.assertEqual(limited.canonical_product_id, "P-LIQUID")
        self.assertEqual(limited.canonical_variant_id, "V-LIQUID-150")
        self.assertEqual(standard.canonical_product_id, "P-LIQUID-BASE")
        self.assertEqual(standard.canonical_variant_id, "V-LIQUID-100")

    def test_verified_gtin_with_wrong_size_stays_unresolved(self):
        result = self.matcher.match(
            RetailerOffer(
                retailer="deloox",
                raw_name="French Avenue Liquid Brun Extrait de Parfum Limited edition 150 ml",
                brand_raw="French Avenue",
                size_ml=100,
                raw_payload={"gtin13": "6298042001831"},
            )
        )
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "verified_gtin_size_conflict")


if __name__ == "__main__":
    unittest.main()
