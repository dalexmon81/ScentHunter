"""SQLAlchemy persistence gate with explicit legacy-ID to UUID resolution."""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID
import pycountry

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Fragrance, IngestionRaw, LegacyProductIdMap, LegacyVariantIdMap,
    MatchAudit, Offer, PriceHistory, ProductVariant, Store,
)

_CURRENCY = re.compile(r"^[A-Z]{3}$")
_ALLOWED_AVAILABILITY = {"in_stock", "out_of_stock"}


class PromotionRejected(ValueError):
    """A staged retailer row failed the publication contract."""


@dataclass(frozen=True)
class ResolvedLegacyIds:
    fragrance_id: UUID
    product_variant_id: UUID


def resolve_legacy_ids(
    session: Session, *, legacy_product_id: str | None,
    legacy_variant_id: str | None,
) -> ResolvedLegacyIds | None:
    """Resolve only explicit persisted mappings; never synthesize UUIDs."""
    if not legacy_product_id or not legacy_variant_id:
        return None
    product_map = session.get(LegacyProductIdMap, legacy_product_id)
    variant_map = session.get(LegacyVariantIdMap, legacy_variant_id)
    if product_map is None or variant_map is None:
        return None
    fragrance = session.get(Fragrance, product_map.fragrance_id)
    variant = session.get(ProductVariant, variant_map.product_variant_id)
    if fragrance is None or variant is None or variant.fragrance_id != fragrance.id:
        return None
    return ResolvedLegacyIds(
        fragrance_id=fragrance.id,
        product_variant_id=variant.id,
    )


def stage_raw_offer(session: Session, *, store_id: UUID, raw_payload: dict,
                    external_product_id: str | None = None) -> UUID:
    """Persist original retailer payload as pending. Caller owns transaction."""
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
                 confidence: Decimal | None = None, reason: str | None = None,
                 unresolved_status: str = "unmatched") -> str:
    """Persist UUID match; unresolved rows never receive a variant UUID."""
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
        if unresolved_status not in {"pending", "unmatched"}:
            raise ValueError("unresolved_status must be pending or unmatched")
        row.status = unresolved_status
        row.product_variant_id = None
        row.match_method = method
        row.match_confidence = confidence
        row.rejection_reason = reason or "no_canonical_variant_match"
    else:
        variant = session.get(ProductVariant, product_variant_id)
        if variant is None:
            raise ValueError("canonical product variant UUID does not exist")
        row.status = "matched"
        row.product_variant_id = variant.id
        row.match_method = method
        row.match_confidence = confidence
        row.rejection_reason = None
    session.flush()
    return row.status


def record_legacy_match(
    session: Session, *, ingestion_raw_id: UUID,
    legacy_product_id: str, legacy_variant_id: str,
    method: str, confidence: Decimal | None = None,
    unresolved_status: str = "unmatched",
) -> ResolvedLegacyIds | None:
    """Persist historical matcher IDs, resolve via DB maps, then assign UUID."""
    row = session.get(IngestionRaw, ingestion_raw_id)
    if row is None:
        raise ValueError("unknown ingestion_raw_id")
    if row.status not in {"pending", "unmatched"}:
        raise ValueError(f"cannot resolve row in status {row.status}")
    row.legacy_product_id = legacy_product_id
    row.legacy_variant_id = legacy_variant_id
    resolved = resolve_legacy_ids(
        session, legacy_product_id=legacy_product_id,
        legacy_variant_id=legacy_variant_id,
    )
    if resolved is None:
        record_match(
            session, ingestion_raw_id=ingestion_raw_id,
            product_variant_id=None, method=method, confidence=confidence,
            reason="legacy_catalog_id_mapping_not_found_or_inconsistent",
            unresolved_status=unresolved_status,
        )
        return None
    record_match(
        session, ingestion_raw_id=ingestion_raw_id,
        product_variant_id=resolved.product_variant_id,
        method=method, confidence=confidence,
    )
    return resolved


def promote_offer(session: Session, *, ingestion_raw_id: UUID, price: Decimal,
                  currency: str, url: str, availability: str, source: str,
                  confidence: Decimal | None = None) -> UUID:
    """Idempotently create/update one store offer and append price history."""
    row = session.get(IngestionRaw, ingestion_raw_id)
    if row is None:
        raise ValueError("unknown ingestion_raw_id")
    if row.status != "matched" or row.product_variant_id is None:
        raise PromotionRejected("only rows with a resolved UUID match can be promoted")
    if row.validation_status != "validated":
        raise PromotionRejected("offer evidence must pass validation before publication")
    store = session.get(Store, row.store_id)
    if store is None or store.status != "active":
        raise PromotionRejected("store is not active")
    if session.get(ProductVariant, row.product_variant_id) is None:
        raise PromotionRejected("canonical product variant UUID does not exist")
    if not isinstance(price, Decimal) or not price.is_finite() or price <= 0:
        raise PromotionRejected("price must be a positive finite Decimal")
    if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency) or (pycountry.currencies.get(alpha_3=currency) is None or currency in {"XXX", "XTS"}):
        raise PromotionRejected("currency must be a valid ISO 4217 code")
    if availability != "in_stock":
        raise PromotionRejected("only explicitly in-stock offers are publishable")
    parsed = urlparse(url or "")
    if parsed.scheme != "https" or not parsed.hostname:
        raise PromotionRejected("offer URL must be absolute HTTPS")
    if not source or not source.strip():
        raise PromotionRejected("source is required")
    if confidence is None or not confidence.is_finite() or confidence < Decimal("0.950") or confidence > 1:
        raise PromotionRejected("match confidence must be at least 0.950")
    payload = row.raw_payload or {}
    captured_value = payload.get("capturedAt") or payload.get("captured_at")
    try:
        captured_at = datetime.fromisoformat(str(captured_value).replace("Z", "+00:00"))
        if captured_at.tzinfo is None:
            raise ValueError("capture timestamp must include timezone")
        now = datetime.now(timezone.utc)
        if captured_at > now + timedelta(minutes=5):
            raise ValueError("capture timestamp is in the future")
        if captured_at < now - timedelta(hours=48):
            raise ValueError("offer evidence is stale")
    except (TypeError, ValueError) as exc:
        raise PromotionRejected(f"invalid or stale capture timestamp: {exc}") from exc
    if payload.get("purchasable") is False or payload.get("isPurchasable") is False:
        raise PromotionRejected("product is not purchasable")
    if payload.get("price_incoherent") is True or payload.get("page_price_mismatch") is True:
        raise PromotionRejected("price and product page evidence is inconsistent")

    # Retailer identity is the idempotency key. Never reuse an unrelated
    # listing merely because it maps to the same canonical variant: a shop may
    # legitimately expose multiple listings, bundles, or seller offers.
    existing = None
    if row.external_product_id:
        existing = session.scalar(select(Offer).where(
            Offer.store_id == row.store_id,
            Offer.external_product_id == row.external_product_id,
        ).order_by(Offer.captured_at.desc()).limit(1))
    else:
        # Legacy rows without an external ID can only be refreshed by their
        # exact URL, not by canonical variant alone.
        existing = session.scalar(select(Offer).where(
            Offer.store_id == row.store_id,
            Offer.url == url,
        ).order_by(Offer.captured_at.desc()).limit(1))
    if existing is not None and existing.product_variant_id != row.product_variant_id:
        raise PromotionRejected(
            "external product identity is already linked to a different canonical variant"
        )

    if existing is None:
        offer = Offer(
            ingestion_raw_id=row.id, store_id=row.store_id,
            product_variant_id=row.product_variant_id,
            external_product_id=row.external_product_id, url=url, price=price,
            currency=currency, availability=availability, source=source,
            confidence=confidence if confidence is not None else row.match_confidence,
            status="active", publication_status="published",
        )
        session.add(offer)
        session.flush()
        session.add(PriceHistory(offer_id=offer.id, price=price,
                                 currency=currency, availability=availability))
        offer_id = offer.id
    else:
        existing.ingestion_raw_id = row.id
        existing.external_product_id = row.external_product_id or existing.external_product_id
        existing.product_variant_id = row.product_variant_id
        existing.url = url
        existing.captured_at = datetime.now(timezone.utc)
        existing.price = price
        existing.currency = currency
        existing.availability = availability
        existing.source = source
        existing.confidence = confidence if confidence is not None else row.match_confidence
        existing.status = "active"
        existing.publication_status = "published"
        # Record every successfully captured observation, including an unchanged
        # price. This makes each normal hydration auditable without creating a
        # second Offer row for the same retailer product.
        session.add(PriceHistory(
            offer_id=existing.id, price=price,
            currency=currency, availability=availability,
        ))
        offer_id = existing.id
        session.flush()

    session.add(MatchAudit(
        offer_id=offer_id, product_variant_id=row.product_variant_id,
        method=row.match_method or "unspecified",
        confidence=confidence if confidence is not None else row.match_confidence,
        reason="promoted_from_resolved_legacy_catalog_ids",
    ))
    row.status = "promoted"
    session.flush()
    return offer_id
