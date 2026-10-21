"""Conservative, catalog-only matcher for the isolated ScentHunter next engine.

Only exact normalized canonical names are eligible. This module does not use
retailer images, prices, scraped identifiers, fuzzy guesses, network calls, or
database writes to establish identity. If identity or format is not sufficiently
certain, the offer remains unresolved or ambiguous.
"""
from __future__ import annotations

import re
import unicodedata
from decimal import Decimal

from .catalog_repository import CatalogRepository
from .models import MatchStatus, OfferMatch, RetailerOffer, CanonicalProduct


_SPACE_RE = re.compile(r"\\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

# Generic descriptors frequently appended to product titles; never product-specific.
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
    """Return conservative forms after removing only a leading brand and generic suffixes."""
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


class CanonicalMatcher:
    """Resolve retailer offers only when canonical name, brand and format are safe."""

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

        candidates: list[CanonicalProduct] = []
        for product in self._catalog.all_products():
            product_name = normalize_identity_text(product.name)
            if not product_name or not any(
                product_name in _name_forms(form, None)
                for form in offer_forms
            ):
                # Compare normalized product name against the generated offer forms
                # directly; no edit-distance or token-only matching is performed.
                if product_name not in offer_forms:
                    continue
            if offer.brand_raw:
                offer_brand = normalize_identity_text(offer.brand_raw)
                product_brand = normalize_identity_text(product.brand)
                if offer_brand != product_brand:
                    continue
            candidates.append(product)

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
                candidate_product_ids=tuple(sorted(item.product_id for item in candidates)),
            )

        product = candidates[0]
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
            if len(matching_variants) == 1:
                variant = matching_variants[0]
                return OfferMatch(
                    offer=offer,
                    status=MatchStatus.MATCHED,
                    canonical_product_id=product.product_id,
                    canonical_variant_id=variant.variant_id,
                    confidence=Decimal("1.0"),
                    reason="exact_name_brand_and_size",
                )
            if len(matching_variants) > 1:
                return OfferMatch(
                    offer=offer,
                    status=MatchStatus.AMBIGUOUS,
                    reason="duplicate_variants_for_explicit_size",
                    candidate_product_ids=(product.product_id,),
                )
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="explicit_size_has_no_canonical_variant",
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
                reason="exact_name_brand_and_only_declared_variant",
            )

        return OfferMatch(
            offer=offer,
            status=MatchStatus.UNRESOLVED,
            reason="format_missing_for_multi_variant_product",
            candidate_product_ids=(product.product_id,),
        )
