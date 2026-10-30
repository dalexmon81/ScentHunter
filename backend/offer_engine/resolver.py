"""Bridge raw retailer observations to the existing canonical matcher.

The connector never assigns canonical IDs. This module delegates identity to
ScentHunter's reviewed catalog matcher and promotes an observation only when
identity, explicit availability and source evidence are all established.
Price publication remains a separate policy decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

try:
    from scenthunter_next_engine.canonical_matcher import CanonicalMatcher
    from scenthunter_next_engine.models import MatchStatus, RetailerOffer
except ModuleNotFoundError:
    from backend.scenthunter_next_engine.canonical_matcher import CanonicalMatcher
    from backend.scenthunter_next_engine.models import MatchStatus, RetailerOffer

from .contracts import Availability, OfferObservation, RetailerListing, Verification


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    observation: OfferObservation
    status: str
    reason: str


def _page_facts(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    page = payload.get("parsed_page")
    if isinstance(page, Mapping):
        return page
    feed_record = payload.get("feed_record")
    return feed_record if isinstance(feed_record, Mapping) else {}


def _size_ml(listing: RetailerListing, page: Mapping[str, Any]) -> int | None:
    attrs = page.get("attributes")
    size = attrs.get("size_ml") if isinstance(attrs, Mapping) else None
    value = size.get("value") if isinstance(size, Mapping) else None
    if value is None:
        value = page.get("size_ml")
    try:
        parsed = int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
    if parsed is not None and parsed <= 0:
        return None
    if listing.raw_size_ml is not None and parsed != listing.raw_size_ml:
        return None
    return parsed


def resolve_observation(
    listing: RetailerListing,
    observation: OfferObservation,
    matcher: CanonicalMatcher,
) -> ResolutionResult:
    """Resolve identity conservatively; never infer stock or price."""
    expected_key = f"{listing.retailer}:{listing.external_id or listing.product_url}"
    if observation.listing_key != expected_key:
        return ResolutionResult(observation, "unresolved", "listing_key_mismatch")

    page = _page_facts(observation.raw_payload or {})
    size_ml = _size_ml(listing, page)
    if listing.raw_size_ml is not None and size_ml is None:
        return ResolutionResult(observation, "unresolved", "variant_size_missing_or_changed")

    raw_name = str(page.get("name") or page.get("title") or listing.raw_title).strip()
    raw_brand = str(page.get("brand") or listing.raw_brand or "").strip() or None
    raw_data = page.get("raw_data")
    identity = page.get("identity")
    matcher_payload: dict[str, Any] = {
        "parsed_product": page,
        "raw_data": raw_data if isinstance(raw_data, Mapping) else {},
        "identity": identity if isinstance(identity, Mapping) else {},
    }
    offer = RetailerOffer(
        retailer=listing.retailer,
        raw_name=raw_name,
        product_url=listing.product_url,
        retailer_product_id=listing.external_id,
        brand_raw=raw_brand,
        size_ml=size_ml,
        price=observation.price,
        currency=observation.currency,
        availability=observation.availability.value,
        raw_payload=matcher_payload,
    )
    match = matcher.match(offer)
    if getattr(match.status, "value", match.status) != MatchStatus.MATCHED.value:
        return ResolutionResult(observation, match.status.value, match.reason or "identity_not_resolved")
    if observation.availability is Availability.UNKNOWN:
        return ResolutionResult(observation, "unresolved", "availability_unknown")
    if not observation.evidence_url or not observation.evidence_hash:
        return ResolutionResult(observation, "unresolved", "evidence_missing")

    # An out-of-stock product can have verified identity and stock state but
    # no price. OfferPolicy separately prevents price-less observations from
    # becoming current purchasable offers.
    verified = OfferObservation(
        listing_key=observation.listing_key,
        observed_at=observation.observed_at,
        # Retailer pages sometimes expose a crossed-out/stale price while the
        # product is explicitly sold out. Preserve it in raw_payload, never as
        # a usable observation price.
        price=None if observation.availability is Availability.OUT_OF_STOCK else observation.price,
        currency=observation.currency,
        availability=observation.availability,
        source=observation.source,
        verification=Verification.VERIFIED,
        product_id=match.canonical_product_id,
        variant_id=match.canonical_variant_id,
        evidence_url=observation.evidence_url,
        evidence_hash=observation.evidence_hash,
        raw_payload=observation.raw_payload,
    )
    return ResolutionResult(verified, "matched", match.reason or "canonical_match")
