"""Orchestration service for the isolated ScentHunter next engine.

This module connects normalization, the read-only canonical catalog, conservative
matching, and aggregation. It does not scrape, access a database, modify files,
or change production behavior.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .canonical_matcher import CanonicalMatcher
from .catalog_repository import CatalogRepository
from .models import OfferMatch, RetailerOffer
from .offer_aggregator import AggregationResult, aggregate_matches
from .offer_normalizer import normalize_offers


@dataclass(frozen=True, slots=True)
class ProcessingResult:
    """Complete auditable result for one batch of raw retailer records."""

    aggregation: AggregationResult
    rejected_rows: tuple[dict[str, Any], ...]
    normalized_offer_count: int

    def __post_init__(self) -> None:
        if self.normalized_offer_count < 0:
            raise ValueError("normalized_offer_count must not be negative")
        if self.normalized_offer_count != self.aggregation.input_count:
            raise ValueError(
                "normalized_offer_count must equal the number of matched records processed"
            )

    @property
    def matched_offer_count(self) -> int:
        return self.aggregation.matched_offer_count

    @property
    def unresolved(self) -> tuple[OfferMatch, ...]:
        return self.aggregation.unresolved

    @property
    def ambiguous(self) -> tuple[OfferMatch, ...]:
        return self.aggregation.ambiguous

    @property
    def groups(self):
        return self.aggregation.groups


class NextEngineService:
    """Run the isolated canonical offer-resolution pipeline in memory."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self._catalog = catalog
        self._matcher = CanonicalMatcher(catalog)

    @classmethod
    def from_catalog_file(cls, path: str | Path) -> "NextEngineService":
        """Build the service from the existing canonical catalog, read-only."""
        return cls(CatalogRepository.from_file(path))

    @property
    def catalog(self) -> CatalogRepository:
        """Expose the read-only catalog view for diagnostics and tests."""
        return self._catalog

    def process_records(
        self,
        records: Iterable[Mapping[str, Any]],
        *,
        retailer: str,
        currency_default: str = "EUR",
    ) -> ProcessingResult:
        """Normalize and resolve a batch, preserving rejected rows separately.

        Invalid rows are returned in ``rejected_rows``. Valid offers are matched
        conservatively and then grouped only by explicit canonical product and
        variant IDs. No source row is silently converted into a guessed match.
        """
        offers, rejected_rows = normalize_offers(
            records,
            retailer=retailer,
            currency_default=currency_default,
        )
        matches = tuple(self._matcher.match(offer) for offer in offers)
        aggregation = aggregate_matches(matches)
        return ProcessingResult(
            aggregation=aggregation,
            rejected_rows=rejected_rows,
            normalized_offer_count=len(offers),
        )

    def process_offers(self, offers: Iterable[RetailerOffer]) -> AggregationResult:
        """Resolve already-normalized offers and return grouped outcomes."""
        return aggregate_matches(self._matcher.match(offer) for offer in offers)
