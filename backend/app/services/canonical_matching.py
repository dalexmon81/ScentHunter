"""Database-native, conservative matching for canonical fragrance variants.

Matching order is exact GTIN, an existing retailer-item association, then a
fully specified deterministic identity. Missing variant attributes never act
as wildcards: they remain unresolved for review.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Brand, Fragrance, Offer, ProductVariant
from app.models.normalization import (
    build_identity, extract_concentration, normalize_brand, normalize_fragrance_name, normalize_text,
)


@dataclass(frozen=True)
class CanonicalMatch:
    product_variant_id: UUID
    method: str
    confidence: Decimal
    reason: str


@dataclass(frozen=True)
class CanonicalMatchResult:
    match: CanonicalMatch | None
    reason: str


def _gtin(value: Any) -> str | None:
    if value is None:
        return None
    digits = re.sub(r"[^0-9]", "", str(value))
    return digits if len(digits) in {8, 12, 13, 14} else None


def resolve_canonical_variant(
    session: Session, *, store_id: UUID, external_product_id: str | None,
    record: dict,
) -> CanonicalMatchResult:
    """Resolve one product using database identities only; never consult legacy IDs."""
    gtin = _gtin(record.get("gtin") or record.get("ean"))
    if gtin:
        rows = session.scalars(select(ProductVariant).where(ProductVariant.gtin == gtin)).all()
        if len(rows) == 1:
            return CanonicalMatchResult(CanonicalMatch(
                rows[0].id, "gtin_exact", Decimal("1.000"), "exact_gtin_match"
            ), "matched")
        if len(rows) > 1:
            return CanonicalMatchResult(None, "ambiguous_gtin")

    external_id = str(external_product_id or record.get("external_product_id") or "").strip()
    if external_id:
        existing = session.scalar(select(Offer).where(
            Offer.store_id == store_id,
            Offer.external_product_id == external_id,
            Offer.product_variant_id.is_not(None),
        ).limit(2))
        if existing is not None:
            return CanonicalMatchResult(CanonicalMatch(
                existing.product_variant_id, "store_external_id",
                Decimal("0.990"), "known_store_external_product_association"
            ), "matched")

    title = record.get("title") or record.get("raw_name")
    brand_value = record.get("brand") or record.get("brand_raw")
    fragrance_value = record.get("fragrance")
    if not fragrance_value and title:
        normalized_title = normalize_text(str(title))
        normalized_brand = normalize_brand(str(brand_value or ""))
        if normalized_title.startswith(normalized_brand + " "):
            normalized_title = normalized_title[len(normalized_brand) + 1:]
        fragrance_value = normalized_title
    concentration = record.get("concentration")
    size_ml = record.get("size_ml")
    if not all((brand_value, fragrance_value, concentration, size_ml, title)):
        return CanonicalMatchResult(None, "incomplete_variant_identity")

    identity = build_identity(
        brand=str(brand_value), fragrance_name=str(fragrance_value),
        title=str(title), concentration=str(concentration), size_ml=size_ml,
        is_tester=record.get("is_tester"), is_refill=record.get("is_refill"),
        is_gift_set=record.get("is_gift_set"), is_mini=record.get("is_mini"),
    )
    if not identity.brand or not identity.fragrance or not identity.concentration or identity.size_ml is None:
        return CanonicalMatchResult(None, "incomplete_normalized_variant_identity")
    # A source title is required so absence of tester/refill/gift/mini markers
    # is an explicit negative rather than an unknown value.
    if any(value is None for value in (
        identity.is_tester, identity.is_refill, identity.is_gift_set, identity.is_mini
    )):
        return CanonicalMatchResult(None, "unknown_sellable_format")

    # Fragrance slugs are not guaranteed to use the same tokenizer. Filter
    # normalized names in Python after narrowing by the exact normalized brand.
    candidates = session.scalars(
        select(ProductVariant)
        .join(Fragrance, ProductVariant.fragrance_id == Fragrance.id)
        .join(Brand, Fragrance.brand_id == Brand.id)
        .where(Brand.normalized_name == normalize_brand(str(brand_value)))
    ).all()
    matched = []
    for variant in candidates:
        fragrance = session.get(Fragrance, variant.fragrance_id)
        if fragrance is None:
            continue
        if normalize_fragrance_name(fragrance.name) != identity.fragrance:
            continue
        if extract_concentration(variant.concentration) != identity.concentration:
            continue
        if (
            variant.size_ml == identity.size_ml
            and variant.is_tester is identity.is_tester
            and variant.is_refill is identity.is_refill
            and variant.is_gift_set is identity.is_gift_set
            and variant.is_mini is identity.is_mini
        ):
            matched.append(variant)
    if len(matched) == 1:
        return CanonicalMatchResult(CanonicalMatch(
            matched[0].id, "deterministic_variant",
            Decimal("0.950"), "exact_normalized_variant_attributes"
        ), "matched")
    if len(matched) > 1:
        return CanonicalMatchResult(None, "ambiguous_canonical_variant")
    return CanonicalMatchResult(None, "no_canonical_variant_match")
