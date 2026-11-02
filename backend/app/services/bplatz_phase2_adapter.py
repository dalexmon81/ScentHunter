"""Explicit Bplatz adapter into the Phase 2 persistence contract.

This module is intentionally not imported by the legacy worker. It can be
invoked by a future worker integration after an explicit rollout decision.
The caller owns the SQLAlchemy transaction and session lifecycle.
"""
from __future__ import annotations

from dataclasses import dataclass
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
    """Stage one parsed Bplatz record and safely promote only a certain match.

    No network requests or canonical catalog writes occur here. The caller
    owns the transaction and decides whether to commit or roll back.
    Unmatched or ambiguous records remain staged and are never published.
    """
    if not isinstance(raw_record, dict):
        raise TypeError("raw_record must be a dict")

    external_id = raw_record.get("sku") or raw_record.get("gtin")
    raw_id = stage_raw_offer(
        session, store_id=store_id, raw_payload=raw_record,
        external_product_id=str(external_id) if external_id else None,
    )

    try:
        normalized = normalize_offer(
            raw_record, retailer="Bplatz", currency_default=currency_default,
        )
    except (TypeError, ValueError) as exc:
        reason = f"normalization_failed:{type(exc).__name__}"
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method="bplatz_phase2_normalizer", reason=reason,
        )
        return BplatzPhase2Result(raw_id, "unmatched", reason=reason)

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
        )
        return BplatzPhase2Result(raw_id, "unmatched", reason=reason)

    group = aggregation.groups[0]
    resolved = record_legacy_match(
        session, ingestion_raw_id=raw_id,
        legacy_product_id=group.canonical_product_id,
        legacy_variant_id=group.canonical_variant_id,
        method="bplatz_next_engine_matcher",
    )
    if resolved is None:
        return BplatzPhase2Result(
            raw_id, "unmatched",
            reason="legacy_catalog_id_mapping_not_found_or_inconsistent",
        )

    if normalized.price is None:
        return BplatzPhase2Result(
            raw_id, "matched", fragrance_id=resolved.fragrance_id,
            product_variant_id=resolved.product_variant_id, reason="missing_price",
        )

    offer_id = promote_offer(
        session, ingestion_raw_id=raw_id, price=normalized.price,
        currency=normalized.currency, url=normalized.product_url or "",
        availability=normalized.availability or "", source="bplatz_parser",
    )
    return BplatzPhase2Result(
        raw_id, "promoted", offer_id=offer_id,
        fragrance_id=resolved.fragrance_id,
        product_variant_id=resolved.product_variant_id,
    )
