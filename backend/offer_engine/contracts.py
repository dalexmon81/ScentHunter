"""Typed contracts for retailer listings and immutable offer observations."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Mapping
from urllib.parse import urlparse

class Availability(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"

class Verification(str, Enum):
    VERIFIED = "verified"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"

def _valid_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

def _aware(value: datetime, field: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")

@dataclass(frozen=True, slots=True)
class RetailerListing:
    retailer: str
    external_id: str | None
    product_url: str
    raw_title: str
    raw_brand: str | None = None
    raw_size_ml: int | None = None
    raw_concentration: str | None = None
    raw_gtin: str | None = None
    market: str = "EU"
    def __post_init__(self):
        if not self.retailer.strip() or not self.raw_title.strip():
            raise ValueError("retailer and raw_title are required")
        if not _valid_url(self.product_url):
            raise ValueError("product_url must be an absolute HTTP(S) URL")
        if self.raw_size_ml is not None and self.raw_size_ml <= 0:
            raise ValueError("raw_size_ml must be positive")

@dataclass(frozen=True, slots=True)
class OfferObservation:
    listing_key: str
    observed_at: datetime
    price: Decimal | None
    currency: str
    availability: Availability
    source: str
    verification: Verification
    product_id: str | None = None
    variant_id: str | None = None
    evidence_url: str | None = None
    evidence_hash: str | None = None
    rejection_reason: str | None = None
    raw_payload: Mapping[str, Any] | None = None
    def __post_init__(self):
        if not self.listing_key.strip() or not self.source.strip():
            raise ValueError("listing_key and source are required")
        _aware(self.observed_at, "observed_at")
        if self.price is not None and (not self.price.is_finite() or self.price < 0):
            raise ValueError("price must be finite and non-negative")
        if len(self.currency) != 3 or not self.currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        if self.verification is Verification.VERIFIED:
            if not self.product_id or not self.variant_id:
                raise ValueError("verified observations require canonical product and variant IDs")
            if self.availability is Availability.UNKNOWN:
                raise ValueError("verified observations require explicit availability")
            if not self.evidence_url or not self.evidence_hash:
                raise ValueError("verified observations require evidence URL and content hash")
        elif self.product_id or self.variant_id:
            raise ValueError("unverified/rejected offers cannot expose canonical IDs")
        if self.evidence_url and not _valid_url(self.evidence_url):
            raise ValueError("evidence_url must be an absolute HTTP(S) URL")
    @classmethod
    def now(cls, **kwargs):
        return cls(observed_at=datetime.now(timezone.utc), **kwargs)
