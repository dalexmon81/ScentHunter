"""Durable, idempotent review queue for uncertain canonical identities.

All operations participate in the caller's transaction. This module never commits.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CanonicalIdentityReview
from app.services.product_normalization import NormalizedProduct, normalize_gtin


def _payload(product: NormalizedProduct) -> dict:
    return {
        "brand": product.brand,
        "fragrance_name": product.fragrance_name,
        "concentration": product.concentration,
        "size_ml": product.size_ml,
        "packaging": product.packaging,
        "canonical_key": product.canonical_key,
    }


def enqueue_identity_review(
    session: Session,
    product: NormalizedProduct,
    *,
    reason: str,
    gtin: object = None,
    source_reference: str | None = None,
) -> CanonicalIdentityReview:
    """Create one pending review item; repeated identical evidence is idempotent."""
    if not reason or len(reason) > 160:
        raise ValueError("review_reason_must_be_1_to_160_characters")
    valid_gtin = normalize_gtin(gtin)
    payload = _payload(product)
    identity = {
        "canonical_key": product.canonical_key,
        "gtin": valid_gtin,
        "reason": reason,
        "source_reference": source_reference,
    }
    fingerprint = sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    existing = session.scalar(
        select(CanonicalIdentityReview).where(
            CanonicalIdentityReview.fingerprint == fingerprint
        )
    )
    if existing is not None:
        return existing
    item = CanonicalIdentityReview(
        fingerprint=fingerprint,
        canonical_key=product.canonical_key,
        normalized_payload=payload,
        supplied_gtin=valid_gtin,
        reason=reason,
        source_reference=source_reference,
        status="pending",
    )
    session.add(item)
    session.flush()
    return item


def resolve_identity_review(
    session: Session,
    review_id,
    *,
    outcome: str,
    reviewed_by: str,
    notes: str | None = None,
) -> CanonicalIdentityReview:
    """Resolve a pending item as approved/rejected/duplicate; never edits catalog."""
    if outcome not in {"approved", "rejected", "duplicate"}:
        raise ValueError("unsupported_review_outcome")
    if not reviewed_by or not reviewed_by.strip():
        raise ValueError("reviewed_by_required")
    item = session.get(CanonicalIdentityReview, review_id)
    if item is None:
        raise LookupError("canonical_identity_review_not_found")
    if item.status != "pending":
        raise ValueError("canonical_identity_review_already_resolved")
    item.status = outcome
    item.reviewed_by = reviewed_by.strip()[:160]
    item.reviewed_at = datetime.now(timezone.utc)
    item.resolution_notes = notes
    session.flush()
    return item
