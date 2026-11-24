"""Isolated adapter for the transitional Next Engine catalog matcher.

All new matching decisions should use canonical_matching first. This adapter
contains the one remaining compatibility bridge to the legacy JSON matcher.
It never persists data or overrides a successful database-native match.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence


class LegacyOfferMatcher(Protocol):
    def process_offers(self, offers: Sequence[Any]) -> Any: ...


@dataclass(frozen=True, slots=True)
class LegacyCatalogMatch:
    legacy_product_id: str | None
    legacy_variant_id: str | None
    reason: str | None


def resolve_legacy_catalog_match(
    matcher: LegacyOfferMatcher, normalized_offer: Any
) -> LegacyCatalogMatch:
    """Return one unambiguous legacy candidate, or a review reason."""
    aggregation = matcher.process_offers([normalized_offer])
    if (
        aggregation.input_count != 1
        or aggregation.matched_offer_count != 1
        or len(aggregation.groups) != 1
        or len(aggregation.groups[0].offers) != 1
    ):
        reasons = [
            item.reason or item.status.value
            for item in (*aggregation.unresolved, *aggregation.ambiguous)
        ]
        return LegacyCatalogMatch(
            legacy_product_id=None,
            legacy_variant_id=None,
            reason=";".join(reasons) or "no_single_canonical_variant_match",
        )

    group = aggregation.groups[0]
    return LegacyCatalogMatch(
        legacy_product_id=group.canonical_product_id,
        legacy_variant_id=group.canonical_variant_id,
        reason=None,
    )
