"""Stable, retailer-neutral contracts for acquisition workers.

No network, persistence, canonical matching or public API side effects live here.
Retailer adapters return evidence; downstream services decide whether it can
become a public offer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping, Protocol, Sequence
from urllib.parse import urlparse


class AdapterStatus(str, Enum):
    SUCCESS = "success"
    VERIFIED_EMPTY = "verified_empty"
    OUT_OF_STOCK = "out_of_stock"
    BLOCKED = "blocked"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    CREDENTIALS_MISSING = "credentials_missing"
    PARSE_ERROR = "parse_error"
    NETWORK_ERROR = "network_error"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class RetailerMarket:
    """One retailer storefront in one explicit country/locale market."""

    retailer_id: str
    market: str
    base_url: str
    currency: str = "EUR"
    locale: str = "en"

    def __post_init__(self) -> None:
        if not self.retailer_id.strip():
            raise ValueError("retailer_id is required")
        if len(self.market) != 2 or not self.market.isalpha():
            raise ValueError("market must be a two-letter country code")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        parsed = urlparse(self.base_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("base_url must be an absolute HTTPS URL")
        if parsed.username or parsed.password:
            raise ValueError("base_url must not contain credentials")


@dataclass(frozen=True, slots=True)
class ProductCandidate:
    """A retailer listing candidate; not yet a canonical product match."""

    retailer_id: str
    market: str
    product_url: str
    retailer_product_id: str | None = None
    discovery_source: str = "unknown"
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.retailer_id.strip():
            raise ValueError("retailer_id is required")
        if len(self.market) != 2 or not self.market.isalpha():
            raise ValueError("market must be a two-letter country code")
        parsed = urlparse(self.product_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("product_url must be an absolute HTTPS URL")
        if self.discovered_at.tzinfo is None:
            raise ValueError("discovered_at must be timezone-aware")


@dataclass(frozen=True, slots=True)
class RawProductObservation:
    """Unresolved product-page evidence returned by a retailer adapter."""

    retailer_id: str
    market: str
    product_url: str
    observed_at: datetime
    raw_title: str
    raw_brand: str | None = None
    raw_size: str | None = None
    raw_concentration: str | None = None
    raw_edition: str | None = None
    price: Decimal | None = None
    currency: str | None = None
    availability: str = "unknown"
    retailer_product_id: str | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    parser_version: str = "unversioned"

    def __post_init__(self) -> None:
        if not self.retailer_id.strip() or not self.raw_title.strip():
            raise ValueError("retailer_id and raw_title are required")
        if len(self.market) != 2 or not self.market.isalpha():
            raise ValueError("market must be a two-letter country code")
        parsed = urlparse(self.product_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("product_url must be an absolute HTTPS URL")
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.price is not None and (not self.price.is_finite() or self.price <= 0):
            raise ValueError("price must be a finite positive amount")
        if self.currency is not None and (
            len(self.currency) != 3 or not self.currency.isalpha()
        ):
            raise ValueError("currency must be a three-letter code")
        if self.availability not in {"in_stock", "out_of_stock", "unknown"}:
            raise ValueError("availability must be in_stock, out_of_stock or unknown")


@dataclass(frozen=True, slots=True)
class AdapterRunResult:
    """One bounded adapter execution; failure is explicit and retailer-local."""

    status: AdapterStatus
    retailer_id: str
    market: str
    started_at: datetime
    finished_at: datetime
    observations: Sequence[RawProductObservation] = ()
    candidates_seen: int = 0
    error_code: str | None = None
    retry_after_seconds: int | None = None
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.retailer_id.strip():
            raise ValueError("retailer_id is required")
        if self.started_at.tzinfo is None or self.finished_at.tzinfo is None:
            raise ValueError("run timestamps must be timezone-aware")
        if self.finished_at < self.started_at:
            raise ValueError("finished_at cannot precede started_at")
        if self.candidates_seen < 0:
            raise ValueError("candidates_seen cannot be negative")
        if self.retry_after_seconds is not None and self.retry_after_seconds < 0:
            raise ValueError("retry_after_seconds cannot be negative")
        if self.status is AdapterStatus.SUCCESS and not self.observations:
            raise ValueError("success requires at least one observation")
        if self.status is not AdapterStatus.SUCCESS and self.observations:
            raise ValueError("non-success result cannot contain publicable observations")
        for observation in self.observations:
            if (observation.retailer_id, observation.market) != (
                self.retailer_id, self.market
            ):
                raise ValueError("observation retailer/market differs from run")


class RetailerAdapter(Protocol):
    """Async adapter boundary; concrete adapters own retailer-specific behavior."""

    market: RetailerMarket

    async def discover(self, query: str) -> AdapterRunResult:
        """Discover candidate listings for a query."""

    async def fetch_product(
        self, candidate: ProductCandidate
    ) -> AdapterRunResult:
        """Fetch and parse one candidate into raw evidence."""
