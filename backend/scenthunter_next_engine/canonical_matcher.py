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
from .models import (
    CanonicalProduct,
    CanonicalVariant,
    MatchStatus,
    OfferMatch,
    RetailerOffer,
)


_SPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_GENERIC_TITLE_SUFFIXES = (
    "eau de parfum",
    "eau de toilette",
    "eau de cologne",
    "parfum",
    "perfume",
    "for men",
    "for women",
    "unisex",
)


def normalize_identity_text(value: str | None) -> str:
    """Normalize spelling, accents and punctuation without fuzzy matching."""
    if not value:
        return ""

    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = value.casefold().replace("&", " and ")
    value = _NON_ALNUM_RE.sub(" ", value)
    return _SPACE_RE.sub(" ", value).strip()


def _strict_name_forms(value: str, brand: str | None) -> set[str]:
    """Return exact normalized forms, including a possible brand prefix."""
    normalized = normalize_identity_text(value)
    if not normalized:
        return set()

    forms = {normalized}
    brand_norm = normalize_identity_text(brand)

    if brand_norm and normalized.startswith(brand_norm + " "):
        forms.add(normalized[len(brand_norm):].strip())

    return forms


def _name_forms(value: str, brand: str | None) -> set[str]:
    """Return strict forms plus conservative generic-suffix fallbacks."""
    forms = _strict_name_forms(value, brand)
    expanded = set(forms)

    for form in tuple(forms):
        for suffix in _GENERIC_TITLE_SUFFIXES:
            if form.endswith(" " + suffix):
                shortened = form[: -(len(suffix) + 1)].strip()
                if shortened:
                    expanded.add(shortened)

    return expanded


def _catalog_forms(
    values: tuple[str, ...] | list[str],
    brand: str,
) -> set[str]:
    forms: set[str] = set()

    for value in values:
        forms.update(_name_forms(value, brand))

    return forms


def _variant_forms(
    variant: CanonicalVariant,
    brand: str,
) -> set[str]:
    values = list(variant.aliases)

    if variant.label:
        values.append(variant.label)

    return _catalog_forms(values, brand)


class CanonicalMatcher:
    """Resolve offers using exact catalog identity, aliases and format data."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self._catalog = catalog

    def match(self, offer: RetailerOffer) -> OfferMatch:
        if not _name_forms(offer.raw_name, offer.brand_raw):
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="empty_normalized_name",
            )

        offer_brand = (
            normalize_identity_text(offer.brand_raw)
            if offer.brand_raw
            else None
        )
        products = self._catalog.all_products()

        def collect_candidates(
            strict: bool,
        ) -> list[
            tuple[CanonicalProduct, tuple[CanonicalVariant, ...]]
        ]:
            candidates: list[
                tuple[CanonicalProduct, tuple[CanonicalVariant, ...]]
            ] = []

            name_forms = _strict_name_forms if strict else _name_forms
            offer_forms = name_forms(
                offer.raw_name,
                offer.brand_raw,
            )

            for product in products:
                if (
                    offer_brand
                    and offer_brand
                    != normalize_identity_text(product.brand)
                ):
                    continue

                product_forms: set[str] = set()

                for value in [product.name, *product.aliases]:
                    product_forms.update(
                        name_forms(value, product.brand)
                    )

                matched_variant_aliases = tuple(
                    variant
                    for variant in product.variants
                    if offer_forms
                    & {
                        form
                        for value in [
                            *variant.aliases,
                            *(
                                [variant.label]
                                if variant.label
                                else []
                            ),
                        ]
                        for form in name_forms(value, product.brand)
                    }
                )

                if (
                    offer_forms & product_forms
                    or matched_variant_aliases
                ):
                    candidates.append(
                        (product, matched_variant_aliases)
                    )

            return candidates

        strict_candidates = collect_candidates(strict=True)

        # Canonical-title priority must compare the complete normalized title.
        # Brand-stripped forms are useful for matching aliases, but must not
        # make "Code" equivalent in priority to the canonical title
        # "Armani Code". Otherwise short titles can create false collisions.
        normalized_offer_title = normalize_identity_text(offer.raw_name)

        strict_canonical_ids = {
            product.product_id
            for product, _matched_variants in strict_candidates
            if normalized_offer_title
            == normalize_identity_text(product.name)
        }

        if strict_canonical_ids:
            # Keep only products whose actual canonical title matches exactly.
            # Do not retain other candidates merely because their brand-stripped
            # forms collide with the offer.
            candidates = [
                (product, variants)
                for product, variants in strict_candidates
                if product.product_id in strict_canonical_ids
            ]
        else:
            # No exact canonical-title hit: use strict aliases plus conservative
            # suffix fallbacks. Multiple plausible products stay ambiguous.
            fallback_candidates = collect_candidates(strict=False)

            by_id = {
                product.product_id: (product, variants)
                for product, variants in fallback_candidates
            }

            for product, variants in strict_candidates:
                by_id[product.product_id] = (product, variants)

            candidates = list(by_id.values())

        if not candidates:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="no_exact_canonical_name_and_brand_match",
            )

        if len(candidates) > 1 and offer.size_ml is not None:
            # A duplicate canonical title is a genuine catalog collision:
            # size must never silently choose between duplicate product records.
            normalized_candidate_titles = {
                normalize_identity_text(product.name)
                for product, _ in candidates
            }
            # Disambiguate only across distinct canonical titles, and only
            # when explicit brand + literal canonical title + size identify
            # exactly one candidate. Aliases and brandless offers cannot do so.
            if len(normalized_candidate_titles) > 1:
                raw_offer_title = " ".join((offer.raw_name or "").split()).casefold()
                raw_offer_brand = " ".join((offer.brand_raw or "").split()).casefold()
                exact_title_and_size = []
                if raw_offer_brand:
                    for candidate_product, candidate_variant_aliases in candidates:
                        canonical_title_matches = (
                            " ".join(candidate_product.name.split()).casefold()
                            == raw_offer_title
                        )
                        explicit_brand_matches = (
                            " ".join(candidate_product.brand.split()).casefold()
                            == raw_offer_brand
                        )
                        size_variants = [
                            variant for variant in candidate_product.variants
                            if variant.size_ml == offer.size_ml
                        ]
                        if (
                            canonical_title_matches
                            and explicit_brand_matches
                            and len(size_variants) == 1
                        ):
                            exact_title_and_size.append(
                                (candidate_product, candidate_variant_aliases)
                            )
                if len(exact_title_and_size) == 1:
                    candidates = exact_title_and_size

        if len(candidates) > 1:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.AMBIGUOUS,
                reason="multiple_canonical_products_match",
                candidate_product_ids=tuple(
                    sorted(product.product_id for product, _ in candidates)
                ),
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
            matching_variants = [
                variant
                for variant in variants
                if variant.size_ml == offer.size_ml
            ]

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

            if (
                matched_variant_aliases
                and selected not in matched_variant_aliases
            ):
                return OfferMatch(
                    offer=offer,
                    status=MatchStatus.UNRESOLVED,
                    reason=(
                        "matched_variant_alias_conflicts_with_explicit_size"
                    ),
                    candidate_product_ids=(product.product_id,),
                )

            return OfferMatch(
                offer=offer,
                status=MatchStatus.MATCHED,
                canonical_product_id=product.product_id,
                canonical_variant_id=selected.variant_id,
                confidence=Decimal("1.0"),
                reason=(
                    "exact_name_brand_alias_and_size"
                    if matched_variant_aliases
                    else "exact_name_brand_and_size"
                ),
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
                reason=(
                    "exact_name_brand_alias_and_only_declared_variant"
                ),
            )

        return OfferMatch(
            offer=offer,
            status=MatchStatus.UNRESOLVED,
            reason="format_missing_for_multi_variant_product",
            candidate_product_ids=(product.product_id,),
        )
