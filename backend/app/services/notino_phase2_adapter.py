"""NOTINO CJ feed adapter for the isolated Phase 2 offer database.

Only exact, unique GTIN matches can be promoted. Unmatched or ambiguous rows are
staged for review. The caller owns the SQLAlchemy transaction; this module does
no network access, schema migration, or production activation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ProductVariant
from app.services.ingestion_persistence import (
    promote_offer, record_match, stage_raw_offer,
)


@dataclass(frozen=True)
class NotinoPhase2Result:
    ingestion_raw_id: UUID
    status: str
    offer_id: UUID | None = None
    product_variant_id: UUID | None = None
    reason: str | None = None


def persist_notino_record(
    session: Session, *, store_id: UUID, raw_record: dict,
) -> NotinoPhase2Result:
    """Stage and promote one Notino record only on a unique exact GTIN match."""
    if not isinstance(raw_record, dict):
        raise TypeError("raw_record must be a dict")

    external_id = str(raw_record.get("external_id") or "").strip() or None
    raw_id = stage_raw_offer(
        session, store_id=store_id, raw_payload=raw_record,
        external_product_id=external_id,
    )

    # A retailer-specific identifier is required for safe idempotent updates.
    # Keep malformed rows in the raw queue rather than publishing an offer whose
    # identity cannot be refreshed without falling back to variant-level matching.
    if external_id is None:
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method="notino_external_id", reason="missing_external_product_id",
            unresolved_status="pending",
        )
        return NotinoPhase2Result(
            raw_id, "pending", reason="missing_external_product_id",
        )

    gtin = str(raw_record.get("gtin") or "").strip()
    variants = session.scalars(
        select(ProductVariant).where(ProductVariant.gtin == gtin)
    ).all() if gtin else []

    if len(variants) != 1:
        reason = "missing_gtin" if not gtin else (
            "gtin_not_in_canonical_catalog" if not variants
            else "gtin_matches_multiple_canonical_variants"
        )
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method="notino_exact_gtin", reason=reason,
            unresolved_status="pending",
        )
        return NotinoPhase2Result(raw_id, "pending", reason=reason)

    variant = variants[0]
    record_match(
        session, ingestion_raw_id=raw_id,
        product_variant_id=variant.id, method="notino_exact_gtin",
        confidence=Decimal("1.000"),
    )

    try:
        price = Decimal(str(raw_record.get("sale_price") or raw_record.get("price")))
    except Exception:
        price = Decimal("0")
    currency = str(raw_record.get("currency") or "").upper()
    availability_raw = str(raw_record.get("availability") or "").casefold()
    availability = {
        "in stock": "in_stock",
        "out of stock": "out_of_stock",
    }.get(availability_raw)
    url = str(raw_record.get("affiliate_url") or "").strip()
    parsed = urlparse(url)

    if not price.is_finite() or price <= 0:
        return NotinoPhase2Result(
            raw_id, "matched", product_variant_id=variant.id,
            reason="invalid_price",
        )
    if currency != "EUR":
        return NotinoPhase2Result(
            raw_id, "matched", product_variant_id=variant.id,
            reason="unexpected_currency",
        )
    if availability is None:
        return NotinoPhase2Result(
            raw_id, "matched", product_variant_id=variant.id,
            reason="availability_not_explicit",
        )
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return NotinoPhase2Result(
            raw_id, "matched", product_variant_id=variant.id,
            reason="invalid_affiliate_url",
        )

    offer_id = promote_offer(
        session, ingestion_raw_id=raw_id, price=price,
        currency=currency, url=url, availability=availability,
        source="cj_notino_fr_feed", confidence=Decimal("1.000"),
        match_existing_by_variant=False,
    )
    return NotinoPhase2Result(
        raw_id, "promoted", offer_id=offer_id,
        product_variant_id=variant.id,
    )
