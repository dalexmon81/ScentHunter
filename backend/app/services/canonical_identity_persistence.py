"""Read-only planning gate for normalized canonical product identities.

This module deliberately does not insert, update, or delete catalog rows.
It produces an explicit plan that a later, separately reviewed writer can use.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, ProductVariant
from app.services.product_normalization import NormalizedProduct, normalize_gtin


@dataclass(frozen=True)
class CanonicalIdentityPlan:
    status: str
    normalized: NormalizedProduct
    brand_id: UUID | None = None
    fragrance_id: UUID | None = None
    product_variant_id: UUID | None = None
    reason: str | None = None

    @property
    def is_safe_to_create(self) -> bool:
        return self.status.startswith("create_")


def _slug(value: str) -> str:
    return "-".join(value.split())


def plan_canonical_identity(
    session: Session,
    normalized: NormalizedProduct,
    *,
    gtin: object = None,
) -> CanonicalIdentityPlan:
    """Inspect the catalog and return a dry-run plan; never mutate the session."""
    brand_slug = _slug(normalized.brand)
    fragrance_slug = _slug(normalized.fragrance_name)
    valid_gtin = normalize_gtin(gtin)

    brand = session.scalar(
        select(Brand).where(Brand.normalized_name == normalized.brand)
    )
    brand_slug_owner = session.scalar(
        select(Brand).where(Brand.slug == brand_slug)
    )
    if brand is not None and brand.slug != brand_slug:
        return CanonicalIdentityPlan(
            "review", normalized, reason="brand_slug_mismatch_requires_review"
        )
    if brand_slug_owner is not None and (
        brand is None or brand_slug_owner.id != brand.id
    ):
        return CanonicalIdentityPlan(
            "review", normalized, reason="brand_slug_collision_requires_review"
        )

    if brand is None:
        return CanonicalIdentityPlan(
            "create_brand", normalized,
            reason="brand_not_present_read_only_plan",
        )

    fragrance = session.scalar(
        select(Fragrance).where(
            Fragrance.brand_id == brand.id,
            Fragrance.slug == fragrance_slug,
        )
    )
    if fragrance is None:
        return CanonicalIdentityPlan(
            "create_fragrance", normalized, brand_id=brand.id,
            reason="fragrance_not_present_read_only_plan",
        )

    variant = session.scalar(
        select(ProductVariant).where(
            ProductVariant.canonical_key == normalized.canonical_key
        )
    )
    if variant is None:
        return CanonicalIdentityPlan(
            "create_variant", normalized, brand_id=brand.id,
            fragrance_id=fragrance.id,
            reason="variant_not_present_read_only_plan",
        )
    if variant.fragrance_id != fragrance.id:
        return CanonicalIdentityPlan(
            "review", normalized, brand_id=brand.id,
            fragrance_id=fragrance.id,
            product_variant_id=variant.id,
            reason="canonical_key_points_to_different_fragrance",
        )

    stored_gtin = normalize_gtin(variant.gtin)
    if valid_gtin and stored_gtin and valid_gtin != stored_gtin:
        return CanonicalIdentityPlan(
            "review", normalized, brand_id=brand.id,
            fragrance_id=fragrance.id, product_variant_id=variant.id,
            reason="different_valid_gtin_requires_review",
        )
    if (valid_gtin is None) != (stored_gtin is None):
        return CanonicalIdentityPlan(
            "review", normalized, brand_id=brand.id,
            fragrance_id=fragrance.id, product_variant_id=variant.id,
            reason="incomplete_gtin_identity_requires_review",
        )

    return CanonicalIdentityPlan(
        "existing", normalized, brand_id=brand.id,
        fragrance_id=fragrance.id, product_variant_id=variant.id,
        reason="existing_identity_matches",
    )
