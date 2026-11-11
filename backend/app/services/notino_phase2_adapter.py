"""NOTINO CJ feed adapter for the isolated Phase 2 offer database.

Only exact, unique GTIN matches can be promoted. Unmatched or ambiguous rows are
staged for review. The caller owns the SQLAlchemy transaction; this module does
no network access, schema migration, or production activation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestionRaw, ProductVariant
from gtin import is_valid_gtin
from app.services.ingestion_persistence import (
    promote_offer, record_match, stage_raw_offer, StaleObservation,
)


@dataclass(frozen=True)
class NotinoPhase2Result:
    ingestion_raw_id: UUID
    status: str
    offer_id: UUID | None = None
    product_variant_id: UUID | None = None
    reason: str | None = None


def _held_matched_result(
    session: Session, *, raw_id: UUID, variant_id: UUID, reason: str,
) -> NotinoPhase2Result:
    """Persist why an exact match was held back from offer publication."""
    raw = session.get(IngestionRaw, raw_id)
    if raw is None:
        raise LookupError(f"staged Notino row not found: {raw_id}")
    raw.rejection_reason = reason
    session.flush()
    return NotinoPhase2Result(
        raw_id, "matched", product_variant_id=variant_id, reason=reason,
    )


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
    if not is_valid_gtin(gtin):
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method="notino_gtin_check_digit", reason="invalid_gtin_check_digit",
            unresolved_status="pending",
        )
        return NotinoPhase2Result(raw_id, "pending", reason="invalid_gtin_check_digit")

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
        return _held_matched_result(session, raw_id=raw_id, variant_id=variant.id, reason="invalid_price")
    if currency != "EUR":
        return _held_matched_result(session, raw_id=raw_id, variant_id=variant.id, reason="unexpected_currency")
    if availability is None:
        return _held_matched_result(session, raw_id=raw_id, variant_id=variant.id, reason="availability_not_explicit")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _held_matched_result(session, raw_id=raw_id, variant_id=variant.id, reason="invalid_affiliate_url")

    source_timestamp = str(raw_record.get("captured_at") or "").strip()
    if not source_timestamp:
        return _held_matched_result(session, raw_id=raw_id, variant_id=variant.id, reason="missing_source_observation_timestamp")
    try:
        observed_at = datetime.fromisoformat(source_timestamp.replace("Z", "+00:00"))
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            raise ValueError("timestamp has no timezone")
        observed_at = observed_at.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return _held_matched_result(session, raw_id=raw_id, variant_id=variant.id, reason="invalid_source_observation_timestamp")

    try:
        offer_id = promote_offer(
            session, ingestion_raw_id=raw_id, price=price,
        currency=currency, url=url, availability=availability,
        source="cj_notino_fr_feed", confidence=Decimal("1.000"),
            match_existing_by_variant=False, observed_at=observed_at,
        )
    except StaleObservation:
        held = _held_matched_result(session, raw_id=raw_id, variant_id=variant.id, reason="source_observation_not_newer_than_stored_offer")
        return NotinoPhase2Result(
            held.ingestion_raw_id, "stale", product_variant_id=variant.id,
            reason=held.reason,
        )
    return NotinoPhase2Result(
        raw_id, "promoted", offer_id=offer_id,
        product_variant_id=variant.id,
    )
