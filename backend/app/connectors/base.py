"""Provider-neutral retailer connector contract.

A connector is an adapter for one retailer. It performs retailer-specific I/O and
parsing only; it must not write to the canonical database or be called from a
user-facing search handler. Worker orchestration owns retries, rate limits,
quarantine, raw-payload retention, and persistence.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


class ConnectorUnavailable(RuntimeError):
    """The retailer feed or endpoint is unavailable at the connector level."""


@dataclass(frozen=True, slots=True)
class DiscoveredProduct:
    """A retailer product reference returned by background discovery."""

    external_product_id: str
    product_url: str
    raw_payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.external_product_id.strip():
            raise ValueError("external_product_id is required")
        parsed = urlparse(self.product_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("product_url must be an absolute HTTP(S) URL")


@dataclass(frozen=True, slots=True)
class ConnectorValidation:
    """Validation outcome for a normalized offer candidate."""

    valid: bool
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.valid and self.errors:
            raise ValueError("a valid result cannot contain validation errors")
        if not self.valid and not self.errors:
            raise ValueError("an invalid result must explain at least one error")


class StoreConnector(ABC):
    """Async contract implemented independently by each retailer adapter.

    Required normalized offer keys for validate_offer:
    product_url, price, currency, availability.
    Availability must be explicit: 'in_stock' or 'out_of_stock'.
    """

    store_key: str

    def __init__(self) -> None:
        key = getattr(self, "store_key", None)
        if not isinstance(key, str) or not key.strip():
            raise ValueError("connector subclasses must define a non-empty store_key")

    @abstractmethod
    async def discover_products(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> Sequence[DiscoveredProduct]:
        """Discover retailer product references for a background ingestion run."""

    @abstractmethod
    async def fetch_product(self, external_product_id: str) -> Mapping[str, Any] | None:
        """Fetch one retailer product record by its stable retailer identifier."""

    @abstractmethod
    async def fetch_offers(self, product_key: str) -> Sequence[Mapping[str, Any]]:
        """Fetch raw offer records associated with a retailer product key."""

    @abstractmethod
    async def fetch_price_and_stock(self, offer_id: str) -> Mapping[str, Any]:
        """Refresh price and availability for one known retailer offer."""

    @abstractmethod
    def parse_raw(self, raw: Mapping[str, Any]) -> Mapping[str, Any]:
        """Convert a retailer-specific raw record into the shared field contract."""

    def validate_offer(self, offer: Mapping[str, Any]) -> ConnectorValidation:
        """Apply the common minimum publication checks; store-specific checks extend this."""
        errors: list[str] = []

        url = offer.get("product_url") or offer.get("url")
        if not isinstance(url, str):
            errors.append("missing_product_url")
        else:
            parsed = urlparse(url.strip())
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                errors.append("invalid_product_url")

        raw_price = offer.get("price")
        try:
            price = Decimal(str(raw_price))
            if not price.is_finite() or price <= 0:
                errors.append("price_must_be_positive")
        except (InvalidOperation, TypeError, ValueError):
            errors.append("missing_or_invalid_price")

        currency = offer.get("currency")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            errors.append("invalid_currency")

        availability = offer.get("availability")
        if availability not in {"in_stock", "out_of_stock"}:
            errors.append("availability_not_explicit")

        return ConnectorValidation(valid=not errors, errors=tuple(errors))
