"""Deterministic aggregation of already-resolved retailer offers.

This module does not perform matching, scrape retailers, read/write a database,
or modify the canonical catalog. Only MATCHED offers are grouped by their real
canonical product and variant IDs. Unresolved and ambiguous offers remain
separate for review and are never guessed into a product group.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .models import MatchStatus, OfferMatch, RetailerOffer


@dataclass(frozen=True, slots=True)
class AggregatedOfferGroup:
    """Offers belonging to one explicit canonical product + variant pair."""

    canonical_product_id: str
    canonical_variant_id: str
    offers: tuple[RetailerOffer, ...]

    def __post_init__(self) -> None:
        if not self.canonical_product_id.strip():
            raise ValueError("canonical_product_id must not be empty")
        if not self.canonical_variant_id.strip():
            raise ValueError("canonical_variant_id must not be empty")
        if not self.offers:
            raise ValueError("an aggregated group must contain at least one offer")


@dataclass(frozen=True, slots=True)
class AggregationResult:
    """Grouped matches plus records requiring review."""

    groups: tuple[AggregatedOfferGroup, ...]
    unresolved: tuple[OfferMatch, ...]
    ambiguous: tuple[OfferMatch, ...]
    input_count: int
    matched_offer_count: int

    def __post_init__(self) -> None:
        if self.input_count < 0 or self.matched_offer_count < 0:
            raise ValueError("counts must not be negative")
        if self.matched_offer_count > self.input_count:
            raise ValueError("matched_offer_count cannot exceed input_count")


def aggregate_matches(matches: Iterable[OfferMatch]) -> AggregationResult:
    """Group only valid MATCHED results; preserve all other results separately.

    Output ordering is deterministic. Offers within a group retain input order.
    This function does not deduplicate offers: deduplication needs an explicit,
    retailer-aware identity policy and must not silently discard source records.
    """
    buckets: dict[tuple[str, str], list[RetailerOffer]] = {}
    unresolved: list[OfferMatch] = []
    ambiguous: list[OfferMatch] = []
    input_count = 0
    matched_offer_count = 0

    for result in matches:
        input_count += 1
        if result.status is MatchStatus.MATCHED:
            # OfferMatch enforces these IDs at construction; guard here as well
            # so future changes cannot accidentally create a guessed group.
            if not result.canonical_product_id or not result.canonical_variant_id:
                unresolved.append(
                    OfferMatch(
                        offer=result.offer,
                        status=MatchStatus.UNRESOLVED,
                        reason="matched_result_missing_canonical_ids",
                    )
                )
                continue
            key = (result.canonical_product_id, result.canonical_variant_id)
            buckets.setdefault(key, []).append(result.offer)
            matched_offer_count += 1
        elif result.status is MatchStatus.AMBIGUOUS:
            ambiguous.append(result)
        else:
            unresolved.append(result)

    groups = tuple(
        AggregatedOfferGroup(
            canonical_product_id=product_id,
            canonical_variant_id=variant_id,
            offers=tuple(buckets[(product_id, variant_id)]),
        )
        for product_id, variant_id in sorted(buckets)
    )
    return AggregationResult(
        groups=groups,
        unresolved=tuple(unresolved),
        ambiguous=tuple(ambiguous),
        input_count=input_count,
        matched_offer_count=matched_offer_count,
    )
