"""Regression tests for sellable product-form classification and matching."""
import json
import tempfile
import unittest
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))

from scenthunter_next_engine.catalog_repository import CatalogRepository
from scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from scenthunter_next_engine.models import MatchStatus, RetailerOffer
from scenthunter_next_engine.offer_normalizer import normalize_offer
from scenthunter_next_engine.product_form import (
    PRODUCT_FORM_VALUES,
    detect_product_form,
    normalize_product_form,
)


class ProductFormGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="scenthunter-product-form-")
        self.root = Path(self.tmp.name)
        self.catalog_path = self.root / "product_catalog.json"
        self.addCleanup(self.tmp.cleanup)

    def write_catalog(self, product_form="fine_fragrance", gtin=None):
        variant = {
            "variant_id": "V-AMBER-250",
            "product_id": "P-AMBER",
            "size_ml": 250,
        }
        if product_form is not None:
            variant["product_form"] = product_form
        if gtin:
            variant["gtin"] = gtin
        self.catalog_path.write_text(json.dumps({
            "products": [{
                "product_id": "P-AMBER",
                "brand_name": "Maison Alhambra",
                "canonical_name": "Amber & Leather",
                "name": "Amber & Leather",
                "aliases": ["Maison Alhambra Amber & Leather"],
                "concentration": "Eau de Parfum",
            }],
            "variants": [variant],
        }), encoding="utf-8")
        return CanonicalMatcher(CatalogRepository.from_file(self.catalog_path))

    def test_product_form_taxonomy_is_controlled(self):
        self.assertEqual(
            PRODUCT_FORM_VALUES,
            {
                "fine_fragrance", "perfume_oil", "deodorant", "body_mist",
                "hair_mist", "body_care", "home_fragrance", "gift_set",
                "discovery_set",
            },
        )
        self.assertEqual(normalize_product_form("Eau de Parfum"), "fine_fragrance")
        self.assertEqual(normalize_product_form("Perfume Oil"), "perfume_oil")
        self.assertEqual(normalize_product_form("reed diffuser"), "home_fragrance")
        self.assertIsNone(normalize_product_form("Beauty"))
        self.assertEqual(detect_product_form("Amber & Leather perfumed deodorant spray"), "deodorant")
        self.assertEqual(detect_product_form("Discovery Set"), "discovery_set")
        self.assertEqual(detect_product_form("Perfumed Deodorant Stick"), "deodorant")
        self.assertEqual(detect_product_form("Rose Hair Mist"), "hair_mist")
        self.assertEqual(detect_product_form("Body Splash"), "body_mist")
        self.assertEqual(detect_product_form("Vanilla Body Butter"), "body_care")
        self.assertEqual(detect_product_form("Oud Room Spray"), "home_fragrance")
        self.assertEqual(detect_product_form("Amber & Leather 100 ml"), None)
        self.assertEqual(detect_product_form("Amber & Leather Spray"), None)

    def test_normalizer_detects_deodorant_and_honors_explicit_form(self):
        inferred = normalize_offer(
            {
                "title": "Maison Alhambra Amber & Leather perfumed deodorant spray 250 ml",
                "brand": "Maison Alhambra",
                "size_ml": 250,
            },
            retailer="test-shop",
        )
        self.assertEqual(inferred.product_form, "deodorant")

        explicit = normalize_offer(
            {
                "title": "Amber & Leather",
                "brand": "Maison Alhambra",
                "size_ml": 250,
                "product_type": "Perfume Oil",
            },
            retailer="test-shop",
        )
        self.assertEqual(explicit.product_form, "perfume_oil")

    def test_deodorant_title_cannot_match_fine_fragrance_variant(self):
        matcher = self.write_catalog("fine_fragrance")
        offer = normalize_offer(
            {
                "title": "Maison Alhambra Amber & Leather perfumed deodorant spray 250 ml",
                "brand": "Maison Alhambra",
                "size_ml": 250,
            },
            retailer="test-shop",
        )
        result = matcher.match(offer)
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "product_form_conflict")
        self.assertIsNone(result.canonical_variant_id)

    def test_deodorant_cannot_match_variant_with_unknown_form(self):
        matcher = self.write_catalog(None)
        offer = normalize_offer(
            {
                "title": "Amber & Leather deodorant spray",
                "brand": "Maison Alhambra",
                "size_ml": 250,
            },
            retailer="test-shop",
        )
        result = matcher.match(offer)
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "canonical_variant_product_form_unverified")

    def test_known_non_fragrance_variant_requires_form_evidence_on_offer(self):
        matcher = self.write_catalog("deodorant")
        offer = RetailerOffer(
            retailer="test-shop",
            raw_name="Amber & Leather",
            brand_raw="Maison Alhambra",
            size_ml=250,
        )
        result = matcher.match(offer)
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "offer_product_form_unverified")

    def test_matching_fine_fragrance_forms_still_match(self):
        matcher = self.write_catalog("fine_fragrance")
        offer = normalize_offer(
            {
                "title": "Amber & Leather Eau de Parfum",
                "brand": "Maison Alhambra",
                "size_ml": 250,
            },
            retailer="test-shop",
        )
        result = matcher.match(offer)
        self.assertEqual(result.status, MatchStatus.MATCHED)
        self.assertEqual(result.canonical_product_id, "P-AMBER")
        self.assertEqual(result.canonical_variant_id, "V-AMBER-250")

    def test_verified_gtin_path_also_rejects_product_form_conflict(self):
        matcher = self.write_catalog("fine_fragrance")
        sidecar = self.root / "scenthunter_next_engine" / "verified_gtin_variant_map.json"
        sidecar.parent.mkdir()
        sidecar.write_text(json.dumps({
            "schema_version": 1,
            "records": [{
                "gtin": "6298042001831",
                "status": "verified",
                "product_id": "P-AMBER",
                "variant_id": "V-AMBER-250",
                "size_ml": 250,
                "source_urls": ["https://example.test/verified-product"],
            }],
        }), encoding="utf-8")
        matcher = CanonicalMatcher(CatalogRepository.from_file(self.catalog_path))
        offer = RetailerOffer(
            retailer="test-shop",
            raw_name="Amber & Leather perfumed deodorant spray",
            brand_raw="Maison Alhambra",
            size_ml=250,
            raw_payload={"gtin13": "6298042001831"},
        )
        result = matcher.match(offer)
        self.assertEqual(result.status, MatchStatus.UNRESOLVED)
        self.assertEqual(result.reason, "product_form_conflict")

    def test_unknown_catalog_product_form_is_not_silently_accepted(self):
        self.write_catalog("deodorizer")
        repository = CatalogRepository.from_file(self.catalog_path)
        self.assertEqual(repository.variant_count(), 0)
        self.assertEqual(repository.skipped_variant_count(), 1)

    def test_only_evidence_checked_variants_are_classified_in_real_seed(self):
        catalog_path = BACKEND / "product_catalog.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        expected = {
            "Maison Alhambra": {
                "Afro Leather", "Alpine Homme Sport", "Anarch", "Anchor Black",
                "Athena", "Aura D'Eclat",
            },
            "French Avenue": {"Aries", "Aquarius"},
        }
        classified = []
        for product in catalog["products"]:
            if product["canonical_name"] not in expected.get(product["brand"], set()):
                continue
            variants = [
                variant for variant in catalog["variants"]
                if variant["product_id"] == product["product_id"]
            ]
            self.assertEqual(len(variants), 1)
            self.assertEqual(variants[0].get("product_form"), "fine_fragrance")
            classified.append((product["brand"], product["canonical_name"]))
        self.assertEqual(len(classified), 8)


if __name__ == "__main__":
    unittest.main()
