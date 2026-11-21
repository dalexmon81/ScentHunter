"""Shared persistence path for structured retailer connectors.

The connector performs retailer-specific parsing; this service stages the
original evidence, resolves only explicit legacy catalog mappings, and publishes
only offers that pass the shared validation gate. The caller owns the transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from sqlalchemy.orm import Session

from app.connectors.base import StoreConnector
from app.models import IngestionRaw
from app.services.canonical_matching import resolve_canonical_variant
from app.services.ingestion_persistence import (
    promote_offer, record_legacy_match, record_match, stage_raw_offer,
)
from scenthunter_next_engine.next_engine_service import NextEngineService
from scenthunter_next_engine.offer_normalizer import normalize_offer


@dataclass(frozen=True)
class ConnectorIngestionResult:
    ingestion_raw_id: UUID
    status: str
    offer_id: UUID | None = None
    product_variant_id: UUID | None = None
    reason: str | None = None


def persist_connector_record(
    session: Session, *, connector: StoreConnector, store_id: UUID,
    raw_record: dict, matcher: NextEngineService,
) -> ConnectorIngestionResult:
    """Stage, normalize, match and optionally publish one connector record.

    No network calls, commits, schema changes, or guessed identity mappings are
    performed here. Unmatched/invalid rows remain in staging for review.
    """
    if not isinstance(raw_record, dict):
        raise TypeError("raw_record must be a dict")

    external_id = (
        raw_record.get("external_product_id")
        or raw_record.get("sku")
        or raw_record.get("gtin")
    )
    raw_payload = dict(raw_record)
    raw_payload["currency_explicit"] = bool(raw_record.get("currency_explicit", False))
    raw_payload["connector_store_key"] = connector.store_key
    raw_id = stage_raw_offer(
        session, store_id=store_id, raw_payload=raw_payload,
        external_product_id=str(external_id) if external_id else None,
    )

    try:
        parsed = connector.parse_raw(raw_record)
        if not isinstance(parsed, dict):
            parsed = dict(parsed)
    except (TypeError, ValueError) as exc:
        reason = f"connector_parse_failed:{type(exc).__name__}:{exc}"
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method=f"{connector.store_key}_connector_parser",
            reason=reason, unresolved_status="pending",
        )
        return ConnectorIngestionResult(raw_id, "pending", reason=reason)

    raw_payload["currency_explicit"] = bool(
        parsed.get("currency_explicit", raw_payload["currency_explicit"])
    )
    if parsed.get("currency_source"):
        raw_payload["currency_source"] = parsed["currency_source"]
    staged = session.get(IngestionRaw, raw_id)
    staged.raw_payload = raw_payload

    try:
        normalized = normalize_offer(parsed, retailer=connector.store_key)
    except (TypeError, ValueError) as exc:
        reason = f"normalization_failed:{type(exc).__name__}:{exc}"
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method=f"{connector.store_key}_connector_normalizer",
            reason=reason, unresolved_status="pending",
        )
        return ConnectorIngestionResult(raw_id, "pending", reason=reason)

    # Prefer database-native canonical identity. The legacy matcher remains a
    # transitional fallback only when the new matcher cannot establish a safe
    # match; it is never allowed to override a successful canonical resolution.
    canonical = resolve_canonical_variant(
        session, store_id=store_id,
        external_product_id=str(external_id) if external_id else None,
        record=parsed,
    )
    if canonical.match is None and canonical.reason != "no_canonical_variant_match":
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method="canonical_database_matcher",
            reason=canonical.reason, unresolved_status="pending",
        )
        return ConnectorIngestionResult(
            raw_id, "pending", reason=canonical.reason,
        )

    if canonical.match is not None:
        resolved_variant_id = canonical.match.product_variant_id
        record_match(
            session, ingestion_raw_id=raw_id,
            product_variant_id=resolved_variant_id,
            method=canonical.match.method,
            confidence=canonical.match.confidence,
            reason=canonical.match.reason,
        )
        validation = connector.validate_offer(parsed)
        if not validation.valid:
            return ConnectorIngestionResult(
                raw_id, "matched", product_variant_id=resolved_variant_id,
                reason=";".join(validation.errors),
            )
        currency_provenance_valid = (
            connector.store_key not in {"orioudh", "parfumcity"}
            or parsed.get("currency_source") == "shopify_cart_presentment_currency"
        )
        if not raw_payload["currency_explicit"] or not currency_provenance_valid:
            return ConnectorIngestionResult(
                raw_id, "matched", product_variant_id=resolved_variant_id,
                reason="currency_not_explicit_in_source",
            )
        if (
            not isinstance(normalized.price, Decimal)
            or not normalized.price.is_finite() or normalized.price <= 0
        ):
            return ConnectorIngestionResult(
                raw_id, "matched", product_variant_id=resolved_variant_id,
                reason="missing_or_invalid_price",
            )
        offer_id = promote_offer(
            session, ingestion_raw_id=raw_id, price=normalized.price,
            currency=normalized.currency, url=normalized.product_url or "",
            availability=normalized.availability or "",
            source=str(parsed.get("source") or f"{connector.store_key}_connector"),
            confidence=canonical.match.confidence,
        )
        return ConnectorIngestionResult(
            raw_id, "promoted", offer_id=offer_id,
            product_variant_id=resolved_variant_id,
        )

    aggregation = matcher.process_offers([normalized])
    if (
        aggregation.input_count != 1 or aggregation.matched_offer_count != 1
        or len(aggregation.groups) != 1 or len(aggregation.groups[0].offers) != 1
    ):
        reasons = [
            item.reason or item.status.value
            for item in (*aggregation.unresolved, *aggregation.ambiguous)
        ]
        reason = ";".join(reasons) or "no_single_canonical_variant_match"
        record_match(
            session, ingestion_raw_id=raw_id, product_variant_id=None,
            method=f"{connector.store_key}_canonical_matcher",
            reason=reason, unresolved_status="pending",
        )
        return ConnectorIngestionResult(raw_id, "pending", reason=reason)

    group = aggregation.groups[0]
    resolved = record_legacy_match(
        session, ingestion_raw_id=raw_id,
        legacy_product_id=group.canonical_product_id,
        legacy_variant_id=group.canonical_variant_id,
        method=f"{connector.store_key}_canonical_matcher",
        unresolved_status="pending",
    )
    if resolved is None:
        return ConnectorIngestionResult(
            raw_id, "pending",
            reason="legacy_catalog_id_mapping_not_found_or_inconsistent",
        )

    validation = connector.validate_offer(parsed)
    if not validation.valid:
        return ConnectorIngestionResult(
            raw_id, "matched", product_variant_id=resolved.product_variant_id,
            reason=";".join(validation.errors),
        )
    if not raw_payload["currency_explicit"]:
        return ConnectorIngestionResult(
            raw_id, "matched", product_variant_id=resolved.product_variant_id,
            reason="currency_not_explicit_in_source",
        )
    if (
        not isinstance(normalized.price, Decimal)
        or not normalized.price.is_finite() or normalized.price <= 0
    ):
        return ConnectorIngestionResult(
            raw_id, "matched", product_variant_id=resolved.product_variant_id,
            reason="missing_or_invalid_price",
        )

    offer_id = promote_offer(
        session, ingestion_raw_id=raw_id, price=normalized.price,
        currency=normalized.currency, url=normalized.product_url or "",
        availability=normalized.availability or "",
        source=str(parsed.get("source") or f"{connector.store_key}_connector"),
    )
    return ConnectorIngestionResult(
        raw_id, "promoted", offer_id=offer_id,
        product_variant_id=resolved.product_variant_id,
    )
