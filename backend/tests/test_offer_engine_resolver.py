from datetime import datetime, timezone
from decimal import Decimal
import unittest

from backend.offer_engine.contracts import (
    Availability, OfferObservation, RetailerListing, Verification,
)
from backend.offer_engine.resolver import resolve_observation
from backend.scenthunter_next_engine.models import MatchStatus, OfferMatch


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
    }
    observation = OfferObservation.now(
        listing_key="deloox:1385920",
        price=None if availability is Availability.OUT_OF_STOCK else Decimal("49.95"),
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
        from backend.offer_engine.policy import OfferPolicy
        self.assertFalse(OfferPolicy().evaluate(result.observation).publish)
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


if __name__ == "__main__":
    unittest.main()
