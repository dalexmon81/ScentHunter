"""Shared offer data contract and safe numeric conversion helpers."""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

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


def decimal_or_none(value: Any) -> Decimal | None:
    """Convert a safe numeric input to Decimal; return None for invalid values."""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None
