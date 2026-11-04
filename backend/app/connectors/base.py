"""Provider-neutral contract for background retailer ingestion.

Connectors return evidence; they never write to the canonical catalog. The
orchestrator owns persistence, retry scheduling, and quarantine decisions.
"""
from __future__ import annotations

import asyncio
import random
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable
from urllib.parse import urlparse


class ConnectorError(RuntimeError):
    """A safe, store-scoped connector failure."""


class ConnectorQuarantined(ConnectorError):
    """Raised when a connector has been quarantined by its orchestrator."""


@dataclass(frozen=True)
class OfferRecord:
    store: str
    external_product_id: str
    brand: str
    fragrance: str
    concentration: str | None
    size_ml: float | None
    gtin: str | None
    title: str
    url: str
    price: Decimal | None
    currency: str | None
    availability: str
    captured_at: str
    source: str
    external_offer_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize using the shared camelCase ingestion payload contract."""
        data = asdict(self)
        return {
            "store": data["store"],
            "externalProductId": data["external_product_id"],
            "externalOfferId": data["external_offer_id"],
            "brand": data["brand"],
            "fragrance": data["fragrance"],
            "concentration": data["concentration"],
            "sizeMl": data["size_ml"],
            "gtin": data["gtin"],
            "title": data["title"],
            "url": data["url"],
            "price": float(data["price"]) if data["price"] is not None else None,
            "currency": data["currency"],
            "availability": data["availability"],
            "capturedAt": data["captured_at"],
            "source": data["source"],
        }


@runtime_checkable
class StoreConnector(Protocol):
    """Async contract implemented independently by each retailer adapter."""
    store_key: str
    source_kind: str

    async def discover_products(self) -> Sequence[Mapping[str, Any]]: ...
    async def fetch_product(self, external_id: str) -> Mapping[str, Any] | None: ...
    async def fetch_offers(self, product_key: str) -> Sequence[OfferRecord]: ...
    async def fetch_price_and_stock(self, offer_id: str) -> OfferRecord | None: ...
    def parse_raw(self, raw: Any) -> Sequence[OfferRecord]: ...
    def validate_offer(self, offer: OfferRecord) -> tuple[bool, tuple[str, ...]]: ...


_REQUIRED_TEXT = ("store", "external_product_id", "brand", "fragrance", "title", "url", "availability", "captured_at", "source")
_ALLOWED_AVAILABILITY = {"in_stock", "out_of_stock", "preorder", "unknown"}


def validate_offer(offer: OfferRecord) -> tuple[bool, tuple[str, ...]]:
    """Validate required evidence without inventing missing price or stock."""
    errors: list[str] = []
    for field in _REQUIRED_TEXT:
        if not str(getattr(offer, field, "") or "").strip():
            errors.append(f"missing_{field}")
    parsed = urlparse(str(offer.url or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        errors.append("invalid_https_url")
    if offer.availability not in _ALLOWED_AVAILABILITY:
        errors.append("invalid_availability")
    if offer.price is None:
        errors.append("missing_price")
    else:
        try:
            price = Decimal(str(offer.price))
            if not price.is_finite() or price <= 0:
                errors.append("invalid_price")
        except (InvalidOperation, TypeError, ValueError):
            errors.append("invalid_price")
    if offer.currency != "EUR":
        errors.append("unsupported_or_missing_currency")
    try:
        timestamp = datetime.fromisoformat(offer.captured_at.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            errors.append("captured_at_timezone_required")
    except (AttributeError, TypeError, ValueError):
        errors.append("invalid_captured_at")
    return not errors, tuple(errors)


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 15.0

    async def run(self, operation, *, sleep=asyncio.sleep, random_value=random.random):
        """Retry transient operations with capped exponential backoff + jitter."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts_must_be_at_least_one")
        for attempt in range(self.max_attempts):
            try:
                return await operation()
            except (TimeoutError, ConnectionError, OSError):
                if attempt + 1 >= self.max_attempts:
                    raise
                delay = min(self.max_delay_seconds, self.base_delay_seconds * (2 ** attempt))
                await sleep(delay * (0.5 + random_value()))


class RateLimiter:
    """Simple async spacing limiter; instantiate one per retailer connector."""
    def __init__(self, requests_per_second: float = 1.0):
        if requests_per_second <= 0:
            raise ValueError("requests_per_second_must_be_positive")
        self.interval = 1.0 / requests_per_second
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def acquire(self, *, monotonic=__import__("time").monotonic, sleep=asyncio.sleep):
        async with self._lock:
            now = monotonic()
            wait = max(0.0, self._last_request + self.interval - now)
            if wait:
                await sleep(wait)
                now = monotonic()
            self._last_request = now


def capture_raw_page_artifact(
    artifacts: list[dict[str, Any]], loaded: Any, *,
    requested_url: str, store_key: str,
) -> bool:
    """Retain exact HTML bytes returned by a page loader, without re-encoding bytes."""
    source_url = str(requested_url or "")
    body = None
    if isinstance(loaded, tuple) and len(loaded) >= 2:
        source_url = str(loaded[0] or source_url)
        body = loaded[1]
    elif isinstance(loaded, (str, bytes, bytearray)):
        body = loaded
    elif isinstance(loaded, Mapping):
        source_url = str(loaded.get("url") or source_url)
        body = loaded.get("html", loaded.get("body"))

    if isinstance(body, str):
        raw = body.encode("utf-8")
        content_type = "text/html; charset=utf-8"
    elif isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
        content_type = "text/html"
    else:
        return False
    if not raw:
        return False

    artifacts.append({
        "format": "html",
        "data": raw,
        "content_type": content_type,
        "source_url": source_url,
        "metadata": {"capture": "page_loader_body", "store": str(store_key)},
    })
    return True
