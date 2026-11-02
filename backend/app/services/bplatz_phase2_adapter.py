"""Bplatz-to-Phase-2 persistence adapter; caller owns the transaction."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.ingestion_persistence import (
    promote_offer, record_legacy_match, record_match, stage_raw_offer,
)
from scenthunter_next_engine.next_engine_service import NextEngineService
from scenthunter_next_engine.offer_normalizer import normalize_offer


@dataclass(frozen=True)
class BplatzPhase2Result:
    ingestion_raw_id: UUID
    status: str
    offer_id: UUID | None = None
    fragrance_id: UUID | None = None
    product_variant_id: UUID | None = None
    reason: str | None = None


def persist_bplatz_record(
    session: Session, *, store_id: UUID, raw_record: dict,
    matcher: NextEngineService, currency_default: str = "EUR",
) -> BplatzPhase2Result:
    """Stage, normalize, match and promote one successfully hydrated Bplatz item.

    The raw record is staged before normalization. Unmatched records stay pending
    for review and never create an offer. The caller owns commit or rollback;
    this function performs no network access or schema migration.
    """
    if not isinstance(raw_record, dict):
        raise TypeError("raw_record must be a dict")

    stable_id = raw_record.get("sku") or raw_record.get("gtin") or raw_record.get("product_url") or raw_record.get("url")
    raw_id = stage_raw_offer(
        session, store_id=store_id, raw_payload=raw_record,
        external_product_id=str(stable_id) if stable_id else None,
    )

    try:
        normalized = normalize_offer(
            raw_record, retailer="Bplatz", currency_default=currency_default,
        )
    except (TypeError, ValueError) as exc:
        reason = f"normalization_failed:{type(exc).__name__}:{exc}"
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method="bplatz_phase2_normalizer", reason=reason,
            unresolved_status="pending",
        )
        return BplatzPhase2Result(raw_id, "pending", reason=reason)

    aggregation = matcher.process_offers([normalized])
    if (aggregation.input_count != 1 or aggregation.matched_offer_count != 1
            or len(aggregation.groups) != 1
            or len(aggregation.groups[0].offers) != 1):
        reasons = [item.reason or item.status.value
                   for item in (*aggregation.unresolved, *aggregation.ambiguous)]
        reason = ";".join(reasons) or "no_single_canonical_variant_match"
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method="bplatz_next_engine_matcher", reason=reason,
            unresolved_status="pending",
        )
        return BplatzPhase2Result(raw_id, "pending", reason=reason)

    group = aggregation.groups[0]
    resolved = record_legacy_match(
        session, ingestion_raw_id=raw_id,
        legacy_product_id=group.canonical_product_id,
        legacy_variant_id=group.canonical_variant_id,
        method="bplatz_next_engine_matcher",
        unresolved_status="pending",
    )
    if resolved is None:
        return BplatzPhase2Result(
            raw_id, "pending",
            reason="legacy_catalog_id_mapping_not_found_or_inconsistent",
        )

    if not isinstance(normalized.price, Decimal) or not normalized.price.is_finite() or normalized.price <= 0:
        return BplatzPhase2Result(
            raw_id, "matched", fragrance_id=resolved.fragrance_id,
            product_variant_id=resolved.product_variant_id, reason="missing_or_invalid_price",
        )
    parsed_url = urlparse(normalized.product_url or "")
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        return BplatzPhase2Result(
            raw_id, "matched", fragrance_id=resolved.fragrance_id,
            product_variant_id=resolved.product_variant_id, reason="missing_or_invalid_url",
        )
    if normalized.availability not in {"in_stock", "out_of_stock"}:
        return BplatzPhase2Result(
            raw_id, "matched", fragrance_id=resolved.fragrance_id,
            product_variant_id=resolved.product_variant_id, reason="availability_not_explicit",
        )

    offer_id = promote_offer(
        session, ingestion_raw_id=raw_id, price=normalized.price,
        currency=normalized.currency, url=normalized.product_url,
        availability=normalized.availability, source="bplatz_parser",
    )
    return BplatzPhase2Result(
        raw_id, "promoted", offer_id=offer_id,
        fragrance_id=resolved.fragrance_id,
        product_variant_id=resolved.product_variant_id,
    )
