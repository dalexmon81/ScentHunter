"""Conservative, catalog-only matcher for the isolated ScentHunter next engine.

Only exact normalized canonical names and explicitly catalogued aliases are
eligible. This module does not use retailer images, prices, fuzzy guesses,
network calls, or database writes to establish identity. If identity or format
is not sufficiently certain, the offer remains unresolved or ambiguous.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from .catalog_repository import CatalogRepository
from .models import CanonicalProduct, CanonicalVariant, MatchStatus, OfferMatch, RetailerOffer


_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_GENERIC_TITLE_SUFFIXES = (
    "eau de parfum", "eau de toilette", "eau de cologne",
    "parfum", "perfume", "for men", "for women", "unisex",
)


def normalize_identity_text(value: str | None) -> str:
    """Normalize spelling, accents and punctuation without fuzzy matching."""
    if not value:
        return ""
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.casefold().replace("&", " and ")
    value = _NON_ALNUM_RE.sub(" ", value)
    return _SPACE_RE.sub(" ", value).strip()


def _name_forms(value: str, brand: str | None) -> set[str]:
    """Return exact normalized forms with only safe leading-brand/suffix removal."""
    normalized = normalize_identity_text(value)
    if not normalized:
        return set()
    forms = {normalized}
    brand_norm = normalize_identity_text(brand)
    if brand_norm and normalized.startswith(brand_norm + " "):
        forms.add(normalized[len(brand_norm):].strip())

    expanded = set(forms)
    for form in tuple(forms):
        for suffix in _GENERIC_TITLE_SUFFIXES:
            if form.endswith(" " + suffix):
                shortened = form[: -(len(suffix) + 1)].strip()
                if shortened:
                    expanded.add(shortened)
    return expanded


def _catalog_forms(values: tuple[str, ...] | list[str], brand: str) -> set[str]:
    forms: set[str] = set()
    for value in values:
        forms.update(_name_forms(value, brand))
    return forms


def _variant_forms(variant: CanonicalVariant, brand: str) -> set[str]:
    values = list(variant.aliases)
    if variant.label:
        values.append(variant.label)
    return _catalog_forms(values, brand)


class CanonicalMatcher:
    """Resolve offers using exact catalog identity, alias, brand and format data."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self._catalog = catalog

    def match(self, offer: RetailerOffer) -> OfferMatch:
        offer_forms = _name_forms(offer.raw_name, offer.brand_raw)
        if not offer_forms:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="empty_normalized_name",
            )

        offer_brand = normalize_identity_text(offer.brand_raw) if offer.brand_raw else None
        candidates: list[tuple[CanonicalProduct, tuple[CanonicalVariant, ...]]] = []
        for product in self._catalog.all_products():
            if offer_brand and offer_brand != normalize_identity_text(product.brand):
                continue

            product_forms = _catalog_forms(
                [product.name, *product.aliases], product.brand
            )
            matched_variant_aliases = tuple(
                variant for variant in product.variants
                if offer_forms & _variant_forms(variant, product.brand)
            )
            if offer_forms & product_forms or matched_variant_aliases:
                candidates.append((product, matched_variant_aliases))

        if not candidates:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="no_exact_canonical_name_and_brand_match",
            )

        if len(candidates) > 1:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.AMBIGUOUS,
                reason="multiple_canonical_products_match",
                candidate_product_ids=tuple(sorted(item[0].product_id for item in candidates)),
            )

        product, matched_variant_aliases = candidates[0]
        variants = product.variants
        if not variants:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="canonical_product_has_no_declared_variants",
                candidate_product_ids=(product.product_id,),
            )

        if offer.size_ml is not None:
            matching_variants = [item for item in variants if item.size_ml == offer.size_ml]
            if not matching_variants:
                return OfferMatch(
                    offer=offer,
                    status=MatchStatus.UNRESOLVED,
                    reason="explicit_size_has_no_canonical_variant",
                    candidate_product_ids=(product.product_id,),
                )
            if len(matching_variants) > 1:
                return OfferMatch(
                    offer=offer,
                    status=MatchStatus.AMBIGUOUS,
                    reason="duplicate_variants_for_explicit_size",
                    candidate_product_ids=(product.product_id,),
                )
            selected = matching_variants[0]
            if matched_variant_aliases and selected not in matched_variant_aliases:
                return OfferMatch(
                    offer=offer,
                    status=MatchStatus.UNRESOLVED,
                    reason="matched_variant_alias_conflicts_with_explicit_size",
                    candidate_product_ids=(product.product_id,),
                )
            return OfferMatch(
                offer=offer,
                status=MatchStatus.MATCHED,
                canonical_product_id=product.product_id,
                canonical_variant_id=selected.variant_id,
                confidence=Decimal("1.0"),
                reason="exact_name_brand_alias_and_size" if matched_variant_aliases else "exact_name_brand_and_size",
            )

        if len(matched_variant_aliases) == 1:
            selected = matched_variant_aliases[0]
            return OfferMatch(
                offer=offer,
                status=MatchStatus.MATCHED,
                canonical_product_id=product.product_id,
                canonical_variant_id=selected.variant_id,
                confidence=Decimal("1.0"),
                reason="exact_variant_alias_and_brand",
            )

        if len(matched_variant_aliases) > 1:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="variant_alias_does_not_identify_unique_format",
                candidate_product_ids=(product.product_id,),
            )

        if len(variants) == 1:
            variant = variants[0]
            return OfferMatch(
                offer=offer,
                status=MatchStatus.MATCHED,
                canonical_product_id=product.product_id,
                canonical_variant_id=variant.variant_id,
                confidence=Decimal("0.95"),
                reason="exact_name_brand_alias_and_only_declared_variant",
            )

        return OfferMatch(
            offer=offer,
            status=MatchStatus.UNRESOLVED,
            reason="format_missing_for_multi_variant_product",
            candidate_product_ids=(product.product_id,),
        )
