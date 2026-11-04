"""Conservative matching from staged retailer evidence to canonical variants."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IngestionRaw, ProductVariant
from app.services.ingestion_persistence import record_match
from app.services.product_normalization import normalize_gtin, normalize_product


@dataclass(frozen=True)
class MatchDecision:
    status: str
    method: str
    confidence: Decimal | None
    product_variant_id: object | None
    reason: str


def decide_offer_match(session: Session, raw: IngestionRaw) -> MatchDecision:
    """Use verified GTIN first, then exact canonical key; never fuzzy-auto-match."""
    payload = raw.raw_payload or {}
    brand = str(payload.get("brand") or "").strip()
    title = str(payload.get("title") or "").strip()
    if not brand or not title:
        return MatchDecision("unmatched", "insufficient_identity", None, None,
                             "missing_brand_or_title")

    try:
        identity = normalize_product(
            brand, title,
            concentration=payload.get("concentration"),
            size_ml=payload.get("sizeMl"),
        )
    except (TypeError, ValueError) as exc:
        return MatchDecision("unmatched", "normalization_review", None, None,
                             str(exc)[:240])

    supplied_gtin = normalize_gtin(payload.get("gtin"))
    if supplied_gtin:
        gtin_candidates = session.scalars(
            select(ProductVariant).where(ProductVariant.gtin == supplied_gtin)
        ).all()
        if len(gtin_candidates) > 1:
            return MatchDecision("unmatched", "gtin_ambiguous", None, None,
                                 "multiple_canonical_variants_share_gtin")
        if len(gtin_candidates) == 1:
            candidate = gtin_candidates[0]
            if candidate.canonical_key != identity.canonical_key:
                return MatchDecision("unmatched", "gtin_identity_conflict", None, None,
                                     "verified_gtin_conflicts_with_normalized_identity")
            return MatchDecision("matched", "gtin_exact", Decimal("1.000"),
                                 candidate.id, "verified_gtin_and_identity_agree")

    candidates = session.scalars(
        select(ProductVariant).where(
            ProductVariant.canonical_key == identity.canonical_key
        )
    ).all()
    if len(candidates) == 1:
        return MatchDecision("matched", "canonical_key_exact", Decimal("0.990"),
                             candidates[0].id, "exact_canonical_key")
    if len(candidates) > 1:
        return MatchDecision("unmatched", "canonical_key_ambiguous", None, None,
                             "multiple_variants_share_canonical_key")
    return MatchDecision("unmatched", "no_exact_match", None, None,
                         "no_exact_canonical_variant")


def match_staged_offer(session: Session, ingestion_raw_id) -> MatchDecision:
    """Persist one conservative match decision; caller controls commit."""
    raw = session.get(IngestionRaw, ingestion_raw_id)
    if raw is None:
        raise LookupError("ingestion_raw_not_found")
    if raw.status not in {"pending", "unmatched"}:
        raise ValueError("ingestion_raw_not_eligible_for_matching")
    decision = decide_offer_match(session, raw)
    record_match(
        session,
        ingestion_raw_id=raw.id,
        product_variant_id=decision.product_variant_id,
        method=decision.method,
        confidence=decision.confidence,
        reason=decision.reason,
        unresolved_status="unmatched",
    )
    return decision
