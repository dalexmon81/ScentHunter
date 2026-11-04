"""Conservative matching from staged retailer evidence to canonical variants."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, IngestionRaw, Offer, ProductVariant
from app.services.ingestion_persistence import record_match
from app.services.product_normalization import normalize_gtin, normalize_product
from app.services.canonical_identity_review_queue import enqueue_identity_review
from app.matching.semantic_matcher import EmbeddingProvider, semantic_candidate_score


@dataclass(frozen=True)
class MatchDecision:
    status: str
    method: str
    confidence: Decimal | None
    product_variant_id: object | None
    reason: str


def _payload_size_ml(payload: dict):
    """Prefer the canonical snake_case field when both legacy aliases exist."""
    if payload.get("size_ml") is not None:
        return payload["size_ml"]
    return payload.get("sizeMl")


def decide_offer_match(
    session: Session, raw: IngestionRaw, *,
    semantic_provider: EmbeddingProvider | None = None,
) -> MatchDecision:
    """Use exact evidence first; semantic matching is opt-in and structurally constrained."""
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
            size_ml=_payload_size_ml(payload),
            packaging=payload.get("packaging"),
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

    if raw.external_product_id:
        linked = session.scalars(
            select(Offer.product_variant_id).where(
                Offer.store_id == raw.store_id,
                Offer.external_product_id == raw.external_product_id,
                Offer.product_variant_id.is_not(None),
            ).distinct()
        ).all()
        linked_ids = set(linked)
        if len(linked_ids) > 1:
            return MatchDecision("unmatched", "store_sku_ambiguous", None, None,
                                 "store_sku_is_linked_to_multiple_variants")
        if len(linked_ids) == 1:
            linked_variant = session.get(ProductVariant, next(iter(linked_ids)))
            if linked_variant is None or linked_variant.canonical_key != identity.canonical_key:
                return MatchDecision("unmatched", "store_sku_identity_conflict", None, None,
                                     "stored_store_sku_mapping_conflicts_with_current_identity")
            return MatchDecision("matched", "store_sku_exact", Decimal("0.995"),
                                 linked_variant.id, "reused_verified_store_sku_mapping")

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

    # Semantic matching is strictly opt-in. Restrict candidates to the exact
    # normalized brand, concentration, size, and packaging before comparing
    # fragrance names. A provider failure or close tie always goes to review.
    if semantic_provider is not None:
        variants = session.scalars(
            select(ProductVariant)
            .join(Fragrance, ProductVariant.fragrance_id == Fragrance.id)
            .join(Brand, Fragrance.brand_id == Brand.id)
            .where(Brand.normalized_name == identity.brand)
        ).all()
        scored: list[tuple[float, ProductVariant]] = []
        expected_packaging = identity.packaging
        packaging_flags = {
            "tester": "is_tester", "refill": "is_refill",
            "gift_set": "is_gift_set", "mini": "is_mini",
        }
        for variant in variants:
            if variant.concentration != identity.concentration:
                continue
            if variant.size_ml != identity.size_ml:
                continue
            actual_packaging = next(
                (kind for kind, attr in packaging_flags.items()
                 if getattr(variant, attr, False) is True),
                "standard",
            )
            if actual_packaging != expected_packaging:
                continue
            fragrance = session.get(Fragrance, variant.fragrance_id)
            if fragrance is None:
                continue
            score = semantic_candidate_score(
                semantic_provider, identity.fragrance_name, fragrance.name,
            )
            if score is not None:
                scored.append((score, variant))
        scored.sort(key=lambda item: item[0], reverse=True)
        if scored:
            best_score, best_variant = scored[0]
            runner_up = scored[1][0] if len(scored) > 1 else -1.0
            if best_score >= 0.985 and best_score - runner_up >= 0.025:
                confidence = Decimal(str(round(best_score, 3)))
                return MatchDecision(
                    "matched", "semantic_embedding", confidence,
                    best_variant.id, "opt_in_semantic_match_above_threshold",
                )
            return MatchDecision(
                "unmatched", "semantic_ambiguous", None, None,
                "semantic_score_below_threshold_or_candidates_too_close",
            )
    return MatchDecision("unmatched", "no_exact_match", None, None,
                         "no_exact_canonical_variant")


def match_staged_offer(
    session: Session, ingestion_raw_id, *,
    semantic_provider: EmbeddingProvider | None = None,
) -> MatchDecision:
    """Persist one conservative match decision; caller controls commit."""
    raw = session.get(IngestionRaw, ingestion_raw_id)
    if raw is None:
        raise LookupError("ingestion_raw_not_found")
    if raw.status not in {"pending", "unmatched"}:
        raise ValueError("ingestion_raw_not_eligible_for_matching")
    decision = decide_offer_match(session, raw, semantic_provider=semantic_provider)
    if decision.status == "unmatched" and decision.method not in {
        "insufficient_identity", "normalization_review"
    }:
        payload = raw.raw_payload or {}
        identity = normalize_product(
            str(payload.get("brand") or ""), str(payload.get("title") or ""),
            concentration=payload.get("concentration"),
            size_ml=_payload_size_ml(payload),
            packaging=payload.get("packaging"),
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
