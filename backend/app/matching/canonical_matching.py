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
from app.catalog.normalization import (
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
    """Normalize and validate GTIN length and GS1 check digit."""
    if value is None:
        return None
    raw = str(value).strip()
    if not re.fullmatch(r"[0-9\s-]+", raw):
        return None
    digits = re.sub(r"[\s-]", "", raw)
    if len(digits) not in {8, 12, 13, 14}:
        return None
    body = [int(char) for char in digits[:-1]]
    weighted_sum = sum(
        digit * (3 if offset % 2 == 0 else 1)
        for offset, digit in enumerate(reversed(body))
    )
    expected = (10 - weighted_sum % 10) % 10
    return digits if expected == int(digits[-1]) else None


def _fragrance_from_title(title: Any, brand_value: Any) -> str:
    """Strip an exact brand prefix and trailing retailer gender descriptors."""
    normalized_title = normalize_text(str(title or ""))
    normalized_brand = normalize_brand(str(brand_value or ""))
    if normalized_brand and normalized_title.startswith(normalized_brand + " "):
        normalized_title = normalized_title[len(normalized_brand) + 1:]
    return re.sub(
        r"\\s+(?:pour\\s+(?:homme|femme)|for\\s+(?:men|women)|mixte|unisexe|unisex)$",
        "",
        normalized_title,
    ).strip()


def _gtin_metadata_conflicts(session: Session, variant: ProductVariant, record: dict) -> list[str]:
    """Reject a valid GTIN when supplied product metadata contradicts its variant."""
    fragrance = session.get(Fragrance, variant.fragrance_id)
    brand = session.get(Brand, fragrance.brand_id) if fragrance is not None else None
    if fragrance is None or brand is None:
        return ["canonical_identity_missing"]

    title = record.get("title") or record.get("raw_name")
    brand_value = record.get("brand") or record.get("brand_raw")
    fragrance_value = record.get("fragrance")
    if not fragrance_value and title:
        fragrance_value = _fragrance_from_title(title, brand_value)

    identity = build_identity(
        brand=str(brand_value) if brand_value else None,
        fragrance_name=str(fragrance_value) if fragrance_value else None,
        title=str(title) if title else None,
        concentration=str(record.get("concentration")) if record.get("concentration") else None,
        size_ml=record.get("size_ml"),
        is_tester=record.get("is_tester"),
        is_refill=record.get("is_refill"),
        is_gift_set=record.get("is_gift_set"),
        is_mini=record.get("is_mini"),
    )
    conflicts: list[str] = []
    if identity.brand and identity.brand != normalize_brand(brand.name):
        conflicts.append("brand")
    if identity.fragrance and identity.fragrance != normalize_fragrance_name(fragrance.name):
        conflicts.append("fragrance")
    canonical_concentration = extract_concentration(variant.concentration)
    if identity.concentration and identity.concentration != canonical_concentration:
        conflicts.append("concentration")
    if identity.size_ml is not None and identity.size_ml != variant.size_ml:
        conflicts.append("size_ml")
    for field_name in ("is_tester", "is_refill", "is_gift_set", "is_mini"):
        source_value = getattr(identity, field_name)
        canonical_value = getattr(variant, field_name)
        if source_value is not None and canonical_value is not None and source_value is not canonical_value:
            conflicts.append(field_name)
    return conflicts


def resolve_canonical_variant(
    session: Session, *, store_id: UUID, external_product_id: str | None,
    record: dict,
) -> CanonicalMatchResult:
    """Resolve one product using database identities only; never consult legacy IDs."""
    raw_gtin = record.get("gtin") or record.get("ean")
    gtin = _gtin(raw_gtin)
    if raw_gtin not in (None, "") and gtin is None:
        return CanonicalMatchResult(None, "invalid_gtin_or_check_digit")
    if gtin:
        rows = session.scalars(select(ProductVariant).where(ProductVariant.gtin == gtin)).all()
        if len(rows) > 1:
            return CanonicalMatchResult(None, "ambiguous_gtin")
        if len(rows) == 1:
            conflicts = _gtin_metadata_conflicts(session, rows[0], record)
            if conflicts:
                return CanonicalMatchResult(
                    None, "gtin_metadata_conflict:" + ",".join(conflicts)
                )
            return CanonicalMatchResult(CanonicalMatch(
                rows[0].id, "gtin_exact", Decimal("1.000"), "exact_gtin_match"
            ), "matched")

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
        fragrance_value = _fragrance_from_title(title, brand_value)
    # Some retailer feeds expose concentration only in the product title
    # (for example "... Eau de Parfum") rather than a dedicated field.
    # Derive it from that explicit source text before declaring the identity
    # incomplete; this keeps the deterministic database match strict.
    concentration = record.get("concentration") or (
        extract_concentration(str(title)) if title else None
    )
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
