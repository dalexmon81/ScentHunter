"""Domain contracts for the isolated ScentHunter next engine.

This module contains data structures only. It does not access the database,
modify product_catalog.json, scrape retailers, or change production behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Mapping


class MatchStatus(str, Enum):
    """Outcome of resolving a retailer offer against the canonical catalog."""

    MATCHED = "matched"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class CanonicalVariant:
    """A real variant explicitly present in the canonical catalog."""

    variant_id: str
    size_ml: int | None = None
    label: str | None = None

    def __post_init__(self) -> None:
        if not self.variant_id.strip():
            raise ValueError("variant_id must not be empty")
        if self.size_ml is not None and self.size_ml <= 0:
            raise ValueError("size_ml must be positive when provided")


@dataclass(frozen=True, slots=True)
class CanonicalProduct:
    """Canonical product identity and its declared variants."""

    product_id: str
    brand: str
    name: str
    variants: tuple[CanonicalVariant, ...] = field(default_factory=tuple)
    canonical_image_url: str | None = None

    def __post_init__(self) -> None:
        if not self.product_id.strip():
            raise ValueError("product_id must not be empty")
        if not self.brand.strip():
            raise ValueError("brand must not be empty")
        if not self.name.strip():
            raise ValueError("name must not be empty")
        ids = [variant.variant_id for variant in self.variants]
        if len(ids) != len(set(ids)):
            raise ValueError("variant_id values must be unique within a product")


@dataclass(frozen=True, slots=True)
class RetailerOffer:
    """Raw retailer listing. It must not be treated as canonical identity."""

    retailer: str
    raw_name: str
    product_url: str | None = None
    retailer_product_id: str | None = None
    brand_raw: str | None = None
    size_ml: int | None = None
    price: Decimal | None = None
    currency: str = "EUR"
    availability: str | None = None
    retailer_image_url: str | None = None
    raw_payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.retailer.strip():
            raise ValueError("retailer must not be empty")
        if not self.raw_name.strip():
            raise ValueError("raw_name must not be empty")
        if self.size_ml is not None and self.size_ml <= 0:
            raise ValueError("size_ml must be positive when provided")
        if self.price is not None and self.price < Decimal("0"):
            raise ValueError("price must not be negative")
        if len(self.currency.strip()) != 3:
            raise ValueError("currency must be a 3-letter code")


@dataclass(frozen=True, slots=True)
class OfferMatch:
    """Resolution result; IDs are canonical only when status is MATCHED."""

    offer: RetailerOffer
    status: MatchStatus
    canonical_product_id: str | None = None
    canonical_variant_id: str | None = None
    confidence: Decimal | None = None
    reason: str | None = None
    candidate_product_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.confidence is not None:
            if not self.confidence.is_finite() or not (
                Decimal("0") <= self.confidence <= Decimal("1")
            ):
                raise ValueError("confidence must be between 0 and 1")
        if self.status is MatchStatus.MATCHED:
            if not self.canonical_product_id:
                raise ValueError("matched offers require canonical_product_id")
            if not self.canonical_variant_id:
                raise ValueError("matched offers require canonical_variant_id")
        elif self.canonical_product_id or self.canonical_variant_id:
            raise ValueError(
                "unresolved or ambiguous offers must not expose canonical IDs"
            )


def decimal_or_none(value: Any) -> Decimal | None:
    """Convert a safe numeric input to Decimal; return None for invalid values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None
