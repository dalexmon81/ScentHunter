"""Explicitly gated writer for canonical product identities.

The writer is opt-in, insert-only, and never commits the caller's transaction.
Production callers must supply an explicit allow_create=True after their own
operational safety checks. Conflicts are returned for review, never merged.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, ProductVariant
from app.services.canonical_identity_persistence import (
    CanonicalIdentityPlan,
    _slug,
    plan_canonical_identity,
)
from app.services.product_normalization import NormalizedProduct, normalize_gtin


def persist_canonical_identity(
    session: Session,
    normalized: NormalizedProduct,
    *,
    gtin: object = None,
    allow_create: bool = False,
) -> CanonicalIdentityPlan:
    """Insert a missing identity only after explicit opt-in; never commit.

    Existing identities are returned unchanged. Ambiguities, invalid supplied
    GTINs, non-integral sizes, and uniqueness races are sent to review.
    """
    if gtin not in (None, "") and normalize_gtin(gtin) is None:
        return CanonicalIdentityPlan(
            "review", normalized, reason="invalid_gtin_requires_review"
        )

    plan = plan_canonical_identity(session, normalized, gtin=gtin)
    if plan.status == "existing" or plan.status == "review":
        return plan
    if not allow_create:
        return CanonicalIdentityPlan(
            "blocked", normalized, reason="explicit_create_opt_in_required"
        )
    if normalized.size_ml is not None and not float(normalized.size_ml).is_integer():
        return CanonicalIdentityPlan(
            "review", normalized, reason="non_integer_variant_size_requires_review"
        )

    try:
        # A savepoint keeps uniqueness races from poisoning the caller's
        # transaction. The outer transaction remains owned by the caller.
        with session.begin_nested():
            brand = session.scalar(
                select(Brand).where(
                    Brand.normalized_name == normalized.brand
                )
            )
            if brand is None:
                brand = Brand(
                    name=normalized.brand.title(),
                    slug=_slug(normalized.brand),
                    normalized_name=normalized.brand,
                )
                session.add(brand)
                session.flush()

            fragrance_slug = _slug(normalized.fragrance_name)
            fragrance = session.scalar(
                __import__("sqlalchemy").select(Fragrance).where(
                    Fragrance.brand_id == brand.id,
                    Fragrance.slug == fragrance_slug,
                )
            )
            if fragrance is None:
                fragrance = Fragrance(
                    brand_id=brand.id,
                    name=normalized.fragrance_name,
                    slug=fragrance_slug,
                )
                session.add(fragrance)
                session.flush()

            variant = session.scalar(
                __import__("sqlalchemy").select(ProductVariant).where(
                    ProductVariant.canonical_key == normalized.canonical_key
                )
            )
            if variant is None:
                variant = ProductVariant(
                    fragrance_id=fragrance.id,
                    concentration=normalized.concentration,
                    size_ml=(
                        int(normalized.size_ml)
                        if normalized.size_ml is not None else None
                    ),
                    is_tester=normalized.is_tester,
                    is_refill=normalized.is_refill,
                    is_gift_set=normalized.is_gift_set,
                    is_mini=normalized.is_mini,
                    gtin=normalize_gtin(gtin),
                    canonical_key=normalized.canonical_key,
                )
                session.add(variant)
                session.flush()

            return CanonicalIdentityPlan(
                "created",
                normalized,
                brand_id=brand.id,
                fragrance_id=fragrance.id,
                product_variant_id=variant.id,
                reason="inserted_in_caller_transaction_not_committed",
            )
    except IntegrityError:
        return CanonicalIdentityPlan(
            "review", normalized, reason="concurrent_identity_creation_requires_review"
        )
