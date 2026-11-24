"""Fetch a known retailer product reference and preserve its raw evidence.

Retailer-specific transport and parsing stay in app.connectors. This module
provides the shared extraction boundary consumed by background workers.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from app.connectors.base import StoreConnector


@dataclass(frozen=True, slots=True)
class ExtractedProductRecord:
    external_product_id: str
    raw_payload: dict[str, Any]


async def extract_product_record(
    connector: StoreConnector, external_product_id: str
) -> ExtractedProductRecord | None:
    """Fetch one known retailer item; return the untouched source record.

    No parsing, canonical matching, persistence or offer publication occurs
    here. A missing product returns None; malformed connector output fails
    closed instead of being silently converted into an empty offer.
    """
    identifier = str(external_product_id or "").strip()
    if not identifier:
        raise ValueError("external_product_id is required")
    raw = await connector.fetch_product(identifier)
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise TypeError("connector fetch_product must return a mapping or None")
    payload = dict(raw)
    if not payload.get("external_product_id"):
        payload["external_product_id"] = identifier
    return ExtractedProductRecord(
        external_product_id=identifier,
        raw_payload=payload,
    )


async def extract_price_stock_observation(
    connector: StoreConnector, external_product_id: str
) -> dict[str, Any]:
    """Fetch one known offer's price/stock evidence without applying pricing rules."""
    identifier = str(external_product_id or "").strip()
    if not identifier:
        raise ValueError("external_product_id is required")
    raw = await connector.fetch_price_and_stock(identifier)
    if not isinstance(raw, Mapping):
        raise TypeError("connector fetch_price_and_stock must return a mapping")
    return dict(raw)
