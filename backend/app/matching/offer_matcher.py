"""Conservative matching from staged retailer evidence to canonical variants."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, IngestionRaw, ProductVariant
from app.services.ingestion_persistence import record_match
from app.services.product_normalization import normalize_gtin, normalize_product
from app.services.canonical_identity_review_queue import enqueue_identity_review


@dataclass(frozen=True)
class MatchDecision:
    status: str
    method: str
    confidence: Decimal | None
    product_variant_id: object | None
    reason: str



def _exact_legacy_attribute_candidates(session: Session, identity):
    """Resolve legacy rows whose stored key predates the canonical-key format.

    This is a strict attribute comparison, not fuzzy matching. The candidate
    must normalize back to the exact same canonical identity, including
    concentration, volume and packaging. Multiple matches remain unresolved.
    """
    fragrance_slug = identity.fragrance_name.replace(" ", "-")
    statement = (
        select(ProductVariant, Fragrance, Brand)
        .join(Fragrance, ProductVariant.fragrance_id == Fragrance.id)
        .join(Brand, Fragrance.brand_id == Brand.id)
        .where(
            Brand.normalized_name == identity.brand,
            Fragrance.slug == fragrance_slug,
        )
    )
    if identity.size_ml is None:
        statement = statement.where(ProductVariant.size_ml.is_(None))
    else:
        statement = statement.where(ProductVariant.size_ml == identity.size_ml)

    matches = []
    for variant, fragrance, brand in session.execute(statement).all():
        packaging_flags = [
            name for name, enabled in (
                ("tester", variant.is_tester),
                ("refill", variant.is_refill),
                ("gift_set", variant.is_gift_set),
                ("mini", variant.is_mini),
            ) if enabled is True
        ]
        if len(packaging_flags) > 1:
            continue
        packaging = packaging_flags[0] if packaging_flags else "standard"
        try:
            candidate = normalize_product(
                brand.name,
                fragrance.name,
                concentration=variant.concentration,
                size_ml=float(variant.size_ml) if variant.size_ml is not None else None,
                packaging=packaging,
            )
        except (TypeError, ValueError):
            continue
        if candidate.canonical_key == identity.canonical_key:
            matches.append(variant)
    return matches

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

    raw_gtin = payload.get("gtin")
    supplied_gtin = normalize_gtin(raw_gtin)
    if raw_gtin is not None and str(raw_gtin).strip() and supplied_gtin is None:
        return MatchDecision("unmatched", "invalid_gtin_review", None, None,
                             "supplied_gtin_failed_length_or_checksum_validation")
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

    # Older catalog imports sometimes retained a legacy key containing the
    # source variant ID. Recover only when the full normalized attributes map
    # to exactly one row; never fall back to name similarity or partial tokens.
    legacy_candidates = _exact_legacy_attribute_candidates(session, identity)
    if len(legacy_candidates) == 1:
        return MatchDecision("matched", "normalized_attributes_exact",
                             Decimal("0.985"), legacy_candidates[0].id,
                             "exact_normalized_attributes_on_legacy_key")
    if len(legacy_candidates) > 1:
        return MatchDecision("unmatched", "normalized_attributes_ambiguous", None, None,
                             "multiple_legacy_variants_share_normalized_identity")
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
    if decision.status == "unmatched" and decision.method not in {
        "insufficient_identity", "normalization_review"
    }:
        payload = raw.raw_payload or {}
        identity = normalize_product(
            str(payload.get("brand") or ""), str(payload.get("title") or ""),
            concentration=payload.get("concentration"),
            size_ml=payload.get("sizeMl"),
        )
        enqueue_identity_review(
            session, identity, reason=decision.method,
            gtin=payload.get("gtin"),
            source_reference=str(raw.external_product_id or raw.id),
        )
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
