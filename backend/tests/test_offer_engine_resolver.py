from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import unittest

from backend.offer_engine.contracts import (
    Availability, OfferObservation, RetailerListing, Verification,
)
from backend.offer_engine.resolver import resolve_observation
from backend.scenthunter_next_engine.models import MatchStatus, OfferMatch, RetailerOffer
from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
from backend.scenthunter_next_engine.catalog_repository import CatalogRepository


class StubMatcher:
    def __init__(self, status=MatchStatus.MATCHED):
        self.status = status
        self.seen_offer = None

    def match(self, offer):
        self.seen_offer = offer
        if self.status is MatchStatus.MATCHED:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.MATCHED,
                canonical_product_id="SH-0031",
                canonical_variant_id="VAR-f5aff76b4bb5de8a",
                reason="verified_gtin_exact_variant",
            )
        return OfferMatch(
            offer=offer,
            status=self.status,
            reason="no_exact_canonical_name_and_brand_match",
        )


def fixture(availability=Availability.OUT_OF_STOCK, size=150):
    listing = RetailerListing(
        retailer="deloox",
        external_id="1385920",
        product_url="https://www.deloox.be/produit/1385920/liquid-brun-limited-edition-150-ml.html",
        raw_title="Liquid Brun Limited Edition Extrait de Parfum 150 ml",
        raw_brand="French Avenue",
        raw_size_ml=150,
        raw_gtin="6298042001831",
        market="BE",
    )
    page = {
        "name": "Liquid Brun Limited Edition Extrait de Parfum 150 ml",
        "brand": "French Avenue",
        "attributes": {"size_ml": {"value": size}},
        "raw_data": {"jsonld": {"gtin13": "6298042001831"}},
        "offer": {"price": "49.95", "availability": availability.value},
    }
    observation = OfferObservation.now(
        listing_key="deloox:1385920",
        price=Decimal("49.95"),
        currency="EUR",
        availability=availability,
        source="product_page",
        verification=Verification.UNVERIFIED,
        evidence_url=listing.product_url,
        evidence_hash="sha256:page-evidence",
        raw_payload={"retailer": "deloox", "parsed_page": page},
    )
    return listing, observation


class OfferEngineResolverTests(unittest.TestCase):
    def test_exact_150ml_match_preserves_sold_out_state(self):
        listing, observation = fixture()
        matcher = StubMatcher()
        result = resolve_observation(listing, observation, matcher)

        self.assertEqual(result.status, "matched")
        self.assertEqual(result.observation.product_id, "SH-0031")
        self.assertEqual(result.observation.variant_id, "VAR-f5aff76b4bb5de8a")
        self.assertEqual(result.observation.availability, Availability.OUT_OF_STOCK)
        self.assertIsNone(result.observation.price)
        self.assertEqual(result.observation.raw_payload["parsed_page"]["offer"]["price"], "49.95")
        from backend.offer_engine.policy import OfferPolicy
        self.assertTrue(OfferPolicy().evaluate(result.observation).publish)
        self.assertEqual(result.observation.verification, Verification.VERIFIED)
        self.assertEqual(matcher.seen_offer.size_ml, 150)
        self.assertEqual(
            matcher.seen_offer.raw_payload["parsed_product"]["raw_data"]["jsonld"]["gtin13"],
            "6298042001831",
        )

    def test_size_change_fails_closed_before_matching(self):
        listing, observation = fixture(size=100)
        matcher = StubMatcher()
        result = resolve_observation(listing, observation, matcher)

        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.reason, "variant_size_missing_or_changed")
        self.assertIsNone(matcher.seen_offer)
        self.assertEqual(result.observation.verification, Verification.UNVERIFIED)

    def test_retailer_brand_and_generic_suffixes_resolve_exact_liquid_brun_variants(self):
        root = Path(__file__).resolve().parents[2]
        catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
        matcher = CanonicalMatcher(catalog)
        cases = (
            (
                "French Avenue Liquid Brun Eau de Parfum Spray (100 ml)",
                100,
                "VAR-f87146c82d167f4c",
            ),
            (
                "Liquid Brun by French Avenue - Men Perfume - EDP - 100 ml",
                100,
                "VAR-f87146c82d167f4c",
            ),
            (
                "Liquid Brun French Avenue 100ML",
                100,
                "VAR-f87146c82d167f4c",
            ),
            (
                "French Avenue Liquid Brun 100ml EDP - Men",
                100,
                "VAR-f87146c82d167f4c",
            ),
            (
                "Liquid Brun Limited Edition French Avenue 150ML",
                150,
                "VAR-f5aff76b4bb5de8a",
            ),
            (
                "Liquid Brun Limited Edition by French Avenue - Extrait de Parfum Men - 150 ml",
                150,
                "VAR-f5aff76b4bb5de8a",
            ),
        )
        for index, (title, size, expected_variant) in enumerate(cases):
            with self.subTest(title=title):
                offer = RetailerOffer(
                    retailer=f"retailer-{index}",
                    raw_name=title,
                    product_url=f"https://example.com/{index}",
                    retailer_product_id=str(index),
                    brand_raw="French Avenue",
                    size_ml=size,
                    price=Decimal("49.95"),
                    currency="EUR",
                    availability="in_stock",
                    raw_payload={},
                )
                match = matcher.match(offer)
                self.assertEqual(match.status, MatchStatus.MATCHED, match.reason)
                self.assertEqual(match.canonical_product_id, "SH-0031" if size == 150 else "SH-0030")
                self.assertEqual(match.canonical_variant_id, expected_variant)

    def test_marketplace_vendor_does_not_override_explicit_canonical_brand_in_title(self):
        root = Path(__file__).resolve().parents[2]
        catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
        matcher = CanonicalMatcher(catalog)
        cases = (
            ("Liquid Brun French Avenue 100ML", 100, "VAR-f87146c82d167f4c"),
            ("Liquid Brun Limited Edition French Avenue 150ML", 150, "VAR-f5aff76b4bb5de8a"),
        )
        for index, (title, size, expected_variant) in enumerate(cases):
            with self.subTest(title=title):
                offer = RetailerOffer(
                    retailer="parfumcity",
                    raw_name=title,
                    product_url=f"https://www.parfumcity.nl/products/{index}",
                    retailer_product_id=str(index),
                    brand_raw="Parfum City",
                    size_ml=size,
                    price=Decimal("49.95"),
                    currency="EUR",
                    availability="in_stock",
                    raw_payload={},
                )
                match = matcher.match(offer)
                self.assertEqual(match.status, MatchStatus.MATCHED, match.reason)
                self.assertEqual(match.canonical_variant_id, expected_variant)

    def test_fractional_size_is_rejected_instead_of_truncated(self):
        listing, observation = fixture(size=150.5)
        matcher = StubMatcher()
        result = resolve_observation(listing, observation, matcher)

        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.reason, "variant_size_missing_or_changed")
        self.assertIsNone(matcher.seen_offer)

    def test_unknown_stock_is_never_promoted_to_verified(self):
        listing, observation = fixture(availability=Availability.UNKNOWN)
        result = resolve_observation(listing, observation, StubMatcher())

        self.assertEqual(result.status, "unresolved")
        self.assertEqual(result.reason, "availability_unknown")
        self.assertEqual(result.observation.verification, Verification.UNVERIFIED)

    def test_ambiguous_identity_is_never_promoted(self):
        listing, observation = fixture()
        result = resolve_observation(
            listing, observation, StubMatcher(status=MatchStatus.AMBIGUOUS)
        )

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual(result.observation.verification, Verification.UNVERIFIED)


    def test_duplicate_profondo_identity_requires_verified_gtin_for_exact_variant(self):
        root = Path(__file__).resolve().parents[2]
        catalog = CatalogRepository.from_file(root / "backend" / "product_catalog.json")
        matcher = CanonicalMatcher(catalog)

        ambiguous_offer = RetailerOffer(
            retailer="retailer-without-gtin",
            raw_name="Giorgio Armani Acqua di Gio Profondo Eau de Parfum 100 ml",
            product_url="https://example.com/profondo-100",
            retailer_product_id="profondo-100",
            brand_raw="Armani",
            size_ml=100,
            price=Decimal("83.95"),
            currency="EUR",
            availability="in_stock",
            raw_payload={},
        )
        ambiguous = matcher.match(ambiguous_offer)
        self.assertEqual(ambiguous.status, MatchStatus.AMBIGUOUS)
        self.assertEqual(
            set(ambiguous.candidate_product_ids),
            {"SH-0043", "SH-AUTO-0019"},
        )

        verified_offer = RetailerOffer(
            retailer="parfumzentrum",
            raw_name="Giorgio Armani Acqua di Gio Profondo Eau de Parfum 100 ml",
            product_url="https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-nachfullbar-100-ml-man_z947818/",
            retailer_product_id="947818",
            brand_raw="Armani",
            size_ml=100,
            gtin="3614273953849",
            price=Decimal("83.95"),
            currency="EUR",
            availability="in_stock",
            raw_payload={"gtin": "3614273953849"},
        )
        verified = matcher.match(verified_offer)
        self.assertEqual(verified.status, MatchStatus.MATCHED)
        self.assertEqual(verified.canonical_product_id, "SH-AUTO-0019")
        self.assertEqual(verified.canonical_variant_id, "VAR-46b03c1f1cff0a6e")
        self.assertEqual(verified.reason, "verified_gtin_exact_variant")


if __name__ == "__main__":
    unittest.main()
