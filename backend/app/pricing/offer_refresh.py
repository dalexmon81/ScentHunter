"""Persist a verified refresh observation without changing canonical identity."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import IngestionRaw, Offer, PriceHistory, Store


def refresh_offer_observation(
    session: Session, *, offer_id: UUID, observation: dict,
    source: str, currency_explicit: bool,
) -> UUID:
    """Update one existing offer and append price history after strict validation.

    The caller owns the transaction. Refresh never changes the canonical variant.
    """
    offer = session.get(Offer, offer_id)
    if offer is None:
        raise ValueError("unknown offer_id")
    store = session.get(Store, offer.store_id)
    if store is None or store.status != "active":
        raise ValueError("offer store is not active")
    if not isinstance(observation, dict):
        raise TypeError("observation must be a dict")

    price = Decimal(str(observation.get("price")))
    if not price.is_finite() or price <= 0:
        raise ValueError("refresh price must be positive and finite")
    currency = observation.get("currency")
    if not isinstance(currency, str) or len(currency) != 3 or currency != currency.upper():
        raise ValueError("refresh currency must be an uppercase ISO code")
    availability = observation.get("availability")
    if availability not in {"in_stock", "out_of_stock"}:
        raise ValueError("refresh availability must be explicit")
    url = str(observation.get("product_url") or observation.get("url") or offer.url).strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("refresh URL must be absolute HTTP(S)")
    if currency != offer.currency:
        raise ValueError("refresh currency changed; manual review required")
    if currency_explicit is not True:
        raise ValueError("refresh currency must be explicit in retailer source")

    source_updated_at = observation.get("source_updated_at")
    if store.slug == "notino-fr" and not source_updated_at:
        raise ValueError("Notino refresh missing retailer source_updated_at")
    captured_at = datetime.now(timezone.utc)
    if source_updated_at:
        try:
            parsed_source_time = datetime.fromisoformat(str(source_updated_at).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("retailer source_updated_at is invalid") from None
        if parsed_source_time.tzinfo is None:
            raise ValueError("retailer source_updated_at must include a timezone")
        captured_at = parsed_source_time.astimezone(timezone.utc)
        if captured_at > datetime.now(timezone.utc):
            raise ValueError("retailer source_updated_at cannot be in the future")
    raw = IngestionRaw(
        store_id=offer.store_id,
        external_product_id=offer.external_product_id,
        raw_payload={"refresh_observation": observation, "source": source,
                     "source_updated_at": source_updated_at,
                     "currency_explicit": True},
        status="promoted",
        product_variant_id=offer.product_variant_id,
        match_method="existing_offer_identity_refresh",
        match_confidence=offer.confidence,
    )
    session.add(raw)
    session.flush()

    offer.ingestion_raw_id = raw.id
    offer.url = url
    offer.price = price
    offer.currency = currency
    offer.availability = availability
    offer.source = source
    offer.captured_at = captured_at
    offer.valid_until = None
    offer.status = "active"
    session.add(PriceHistory(
        offer_id=offer.id, price=price, currency=currency,
        availability=availability, captured_at=captured_at,
    ))
    session.flush()
    return offer.id
