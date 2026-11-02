"""Isolated SQLAlchemy persistence gate for normalized retailer offers."""
from __future__ import annotations

import re
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestionRaw, MatchAudit, Offer, PriceHistory, ProductVariant, Store

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_ALLOWED_AVAILABILITY = {"in_stock", "out_of_stock"}


class PromotionRejected(ValueError):
    """A staged retailer row failed the publication contract."""


def stage_raw_offer(session: Session, *, store_id: UUID, raw_payload: dict,
                    external_product_id: str | None = None) -> UUID:
    """Persist the original payload as pending. The caller owns the transaction."""
    if not isinstance(raw_payload, dict):
        raise TypeError("raw_payload must be a dict")
    if session.get(Store, store_id) is None:
        raise ValueError("unknown store_id")
    row = IngestionRaw(store_id=store_id, raw_payload=raw_payload,
                       external_product_id=external_product_id, status="pending")
    session.add(row)
    session.flush()
    return row.id


def record_match(session: Session, *, ingestion_raw_id: UUID,
                 product_variant_id: UUID | None, method: str,
                 confidence: Decimal | None = None, reason: str | None = None) -> str:
    """Persist matched/unmatched decision; never assign IDs to unresolved rows."""
    row = session.get(IngestionRaw, ingestion_raw_id)
    if row is None:
        raise ValueError("unknown ingestion_raw_id")
    if row.status not in {"pending", "unmatched"}:
        raise ValueError(f"cannot match row in status {row.status}")
    if not method or not method.strip():
        raise ValueError("match method is required")
    if confidence is not None and (not confidence.is_finite() or not 0 <= confidence <= 1):
        raise ValueError("confidence must be between 0 and 1")
    if product_variant_id is None:
        row.status = "unmatched"
        row.product_variant_id = None
        row.match_method = method
        row.match_confidence = confidence
        row.rejection_reason = reason or "no_canonical_variant_match"
    else:
        if session.get(ProductVariant, product_variant_id) is None:
            raise ValueError("canonical product variant does not exist in database")
        row.status = "matched"
        row.product_variant_id = product_variant_id
        row.match_method = method
        row.match_confidence = confidence
        row.rejection_reason = None
    session.flush()
    return row.status


def promote_offer(session: Session, *, ingestion_raw_id: UUID, price: Decimal,
                  currency: str, url: str, availability: str, source: str,
                  confidence: Decimal | None = None) -> UUID:
    """Create offer, price history and match audit in the caller's transaction."""
    row = session.get(IngestionRaw, ingestion_raw_id)
    if row is None:
        raise ValueError("unknown ingestion_raw_id")
    if row.status != "matched" or row.product_variant_id is None:
        raise PromotionRejected("only matched rows with a canonical variant can be promoted")
    store = session.get(Store, row.store_id)
    if store is None or store.status != "active":
        raise PromotionRejected("store is not active")
    if session.get(ProductVariant, row.product_variant_id) is None:
        raise PromotionRejected("canonical product variant does not exist")
    if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
        raise PromotionRejected("price must be a positive finite Decimal")
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
        raise PromotionRejected("currency must be an uppercase ISO 4217 code")
    if availability not in _ALLOWED_AVAILABILITY:
        raise PromotionRejected("availability must be explicit")
    parsed = urlparse(url or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PromotionRejected("offer URL must be absolute HTTP(S)")
    if not source or not source.strip():
        raise PromotionRejected("source is required")
    if confidence is not None and (not confidence.is_finite() or not 0 <= confidence <= 1):
        raise PromotionRejected("confidence must be between 0 and 1")
    if row.external_product_id:
        duplicate = session.scalar(select(Offer.id).where(
            Offer.store_id == row.store_id,
            Offer.external_product_id == row.external_product_id))
        if duplicate is not None:
            raise PromotionRejected("store/external product already has a published offer")

    offer = Offer(
        ingestion_raw_id=row.id, store_id=row.store_id,
        product_variant_id=row.product_variant_id,
        external_product_id=row.external_product_id, url=url, price=price,
        currency=currency, availability=availability, source=source,
        confidence=confidence if confidence is not None else row.match_confidence,
        status="active",
    )
    session.add(offer)
    session.flush()
    session.add(PriceHistory(offer_id=offer.id, price=price,
                             currency=currency, availability=availability))
    session.add(MatchAudit(
        offer_id=offer.id, product_variant_id=row.product_variant_id,
        method=row.match_method or "unspecified", confidence=offer.confidence,
        reason="promoted_from_validated_ingestion_raw"))
    row.status = "promoted"
    session.flush()
    return offer.id
