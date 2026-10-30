"""Conservative, catalog-only matcher for the isolated ScentHunter next engine.

Only exact normalized canonical names and explicitly catalogued aliases are
eligible. This module does not use retailer images, prices, fuzzy guesses,
network calls, or database writes to establish identity. If identity or format
is not sufficiently certain, the offer remains unresolved or ambiguous.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from pathlib import Path

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
    "edp",
    "edt",
    "edc",
    "extrait",
    "spray",
    "men perfume",
    "women perfume",
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


_SIZE_SUFFIX_RE = re.compile(r"\s+\d+(?:[.,]\d+)?\s*(?:ml|cl|dl|l|oz|fl\s*oz)\s*[)\]]*$")
_RETAILER_GENDER_SUFFIXES = {"man", "men", "herren", "heren", "male", "woman", "women", "damen", "dames", "female", "homme", "femme", "unisex"}


def _retailer_title_core(value: str) -> str:
    """Strip only generic retailer suffix metadata; preserve variant qualifiers.

    This handles titles such as "... Eau de Parfum 125 ml (man)" while
    deliberately retaining words such as "refill"/"nachfüllbar", which can
    distinguish a different sellable product.
    """
    core = normalize_identity_text(value)
    # Concentration is a separate canonical attribute, not part of the
    # product name. Remove explicit concentration markers wherever retailers
    # place them; _explicit_concentration() still preserves this evidence for
    # disambiguating products that share a name.
    core = re.sub(
        r"\\b(?:eau de parfum|eau de toilette|eau de cologne|extrait de parfum|edp|edt|edc)\\b",
        " ",
        core,
    )
    core = _SPACE_RE.sub(" ", core).strip()
    changed = True
    while core and changed:
        changed = False
        parts = core.split()
        if parts and parts[-1] in _RETAILER_GENDER_SUFFIXES:
            core = " ".join(parts[:-1]).strip()
            changed = True
            continue
        sized = _SIZE_SUFFIX_RE.sub("", core).strip()
        if sized != core:
            core = sized
            changed = True
            continue
        for suffix in _GENERIC_TITLE_SUFFIXES:
            if core.endswith(" " + suffix):
                core = core[: -(len(suffix) + 1)].strip()
                changed = True
                break
    return core


_BRAND_ALIASES = {
    # Retailer feeds commonly use the parent brand while the catalog stores
    # the product brand. Exact alias only: do not collapse Emporio Armani.
    "giorgio armani": "armani",
}


def normalize_brand_text(value: str | None) -> str:
    normalized = normalize_identity_text(value)
    return _BRAND_ALIASES.get(normalized, normalized)


_CONCENTRATION_ALIASES = {
    "eau de parfum": "eau de parfum",
    "edp": "eau de parfum",
    "eau de toilette": "eau de toilette",
    "edt": "eau de toilette",
    "eau de cologne": "eau de cologne",
    "edc": "eau de cologne",
    "extrait de parfum": "extrait de parfum",
    "parfum": "parfum",
    "perfume": "parfum",
}


def _explicit_concentration(value: str | None) -> str | None:
    """Extract only explicit, unambiguous concentration tokens from an offer title."""
    normalized = normalize_identity_text(value)
    if not normalized:
        return None
    for phrase in (
        "extrait de parfum",
        "eau de parfum",
        "eau de toilette",
        "eau de cologne",
    ):
        if phrase in normalized:
            return _CONCENTRATION_ALIASES[phrase]
    tokens = set(normalized.split())
    if "edp" in tokens:
        return _CONCENTRATION_ALIASES["edp"]
    if "edt" in tokens:
        return _CONCENTRATION_ALIASES["edt"]
    if "edc" in tokens:
        return _CONCENTRATION_ALIASES["edc"]
    if "parfum" in tokens:
        return _CONCENTRATION_ALIASES["parfum"]
    return None


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


def _offer_name_forms(value: str, brand: str | None) -> set[str]:
    """Normalize explicit retailer metadata while preserving product qualifiers."""
    forms = _strict_name_forms(value, brand)
    core = _retailer_title_core(value)
    if core:
        forms.add(core)
        brand_norm = normalize_identity_text(brand)
        if brand_norm and core.startswith(brand_norm + " "):
            forms.add(core[len(brand_norm):].strip())
    brand_norm = normalize_identity_text(brand)
    if brand_norm:
        # Retailers place the explicitly parsed brand at the beginning, middle,
        # or after "by". Remove only that exact brand phrase; keep the original
        # forms above so a brand token that is genuinely part of a product name
        # remains available for exact matching.
        without_brand = re.sub(
            rf"\b{re.escape(brand_norm)}\b",
            " ",
            normalize_identity_text(value),
        )
        without_brand = re.sub(r"\bby\b", " ", without_brand)
        normalized_core = _retailer_title_core(without_brand)
        if normalized_core:
            forms.add(normalized_core)
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


def _validated_gtin(value: object) -> str | None:
    """Return a valid GTIN with check digit, or None for untrusted values."""
    if value is None or isinstance(value, (dict, list, tuple, bool)):
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) not in {8, 12, 13, 14}:
        return None
    total = 0
    for offset, digit in enumerate(reversed(digits[:-1])):
        total += int(digit) * (3 if offset % 2 == 0 else 1)
    expected = (10 - total % 10) % 10
    return digits if expected == int(digits[-1]) else None


def _offer_gtin(raw_payload: Mapping[str, object]) -> str | None:
    """Extract explicit GTIN/EAN from normalized records or nested retailer JSON-LD.

    Deloox exposes the identifier as JSON-LD gtin14 inside raw_data.jsonld.
    Never infer a GTIN from SKU or another generic retailer identifier.
    """
    identity = raw_payload.get("identity")
    raw_data = raw_payload.get("raw_data")
    jsonld = raw_data.get("jsonld") if isinstance(raw_data, Mapping) else None
    parsed_product = raw_payload.get("parsed_product")
    parsed_identity = (
        parsed_product.get("identity")
        if isinstance(parsed_product, Mapping)
        else None
    )
    candidates = [
        raw_payload.get("gtin14"),
        raw_payload.get("gtin13"),
        raw_payload.get("gtin12"),
        raw_payload.get("gtin"),
        raw_payload.get("ean13"),
        raw_payload.get("ean"),
        identity.get("gtin") if isinstance(identity, Mapping) else None,
        identity.get("gtin14") if isinstance(identity, Mapping) else None,
        identity.get("gtin13") if isinstance(identity, Mapping) else None,
        identity.get("gtin12") if isinstance(identity, Mapping) else None,
        parsed_identity.get("gtin") if isinstance(parsed_identity, Mapping) else None,
        parsed_identity.get("gtin14") if isinstance(parsed_identity, Mapping) else None,
        parsed_identity.get("gtin13") if isinstance(parsed_identity, Mapping) else None,
        parsed_identity.get("gtin12") if isinstance(parsed_identity, Mapping) else None,
        parsed_product.get("gtin") if isinstance(parsed_product, Mapping) else None,
        parsed_product.get("gtin14") if isinstance(parsed_product, Mapping) else None,
        parsed_product.get("gtin13") if isinstance(parsed_product, Mapping) else None,
        parsed_product.get("gtin12") if isinstance(parsed_product, Mapping) else None,
    ]
    if isinstance(parsed_product, Mapping):
        parsed_raw_data = parsed_product.get("raw_data")
        parsed_jsonld = parsed_raw_data.get("jsonld") if isinstance(parsed_raw_data, Mapping) else None
        if isinstance(parsed_jsonld, Mapping):
            candidates.extend([
                parsed_jsonld.get("gtin14"),
                parsed_jsonld.get("gtin13"),
                parsed_jsonld.get("gtin12"),
                parsed_jsonld.get("gtin"),
            ])
    if isinstance(jsonld, Mapping):
        candidates.extend([
            jsonld.get("gtin14"),
            jsonld.get("gtin13"),
            jsonld.get("gtin12"),
            jsonld.get("gtin"),
        ])
    for candidate in candidates:
        if isinstance(candidate, Mapping):
            candidate = candidate.get("value")
        normalized = _validated_gtin(candidate)
        if normalized:
            return normalized
    return None


class CanonicalMatcher:
    """Resolve offers using exact catalog identity, aliases, formats and verified GTINs."""

    def __init__(self, catalog: CatalogRepository) -> None:
        self._catalog = catalog
        registry_path = (
            catalog.source.parent
            / "scenthunter_next_engine"
            / "verified_gtin_variant_map.json"
        )
        self._gtin_registry = self._load_gtin_registry(registry_path)

    @staticmethod
    def _load_gtin_registry(path: Path) -> dict[str, dict[str, object]]:
        """Load reviewed GTIN-to-variant evidence; absent sidecars are allowed."""
        if not path.is_file():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Cannot read verified GTIN registry: {path}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise ValueError("Verified GTIN registry has an unsupported schema")
        records = data.get("records")
        if not isinstance(records, list):
            raise ValueError("Verified GTIN registry records must be a list")
        registry: dict[str, dict[str, object]] = {}
        for record in records:
            if not isinstance(record, dict) or record.get("status") != "verified":
                continue
            gtin = _validated_gtin(record.get("gtin"))
            product_id = record.get("product_id")
            variant_id = record.get("variant_id")
            source_urls = record.get("source_urls")
            if (
                not gtin
                or not isinstance(product_id, str)
                or not product_id.strip()
                or not isinstance(variant_id, str)
                or not variant_id.strip()
                or not isinstance(source_urls, list)
                or not source_urls
            ):
                raise ValueError("Verified GTIN records require valid IDs and source URLs")
            if gtin in registry and (
                registry[gtin]["product_id"] != product_id
                or registry[gtin]["variant_id"] != variant_id
            ):
                raise ValueError(f"Conflicting canonical targets for GTIN {gtin}")
            registry[gtin] = record
        return registry

    def _match_verified_gtin(self, offer: RetailerOffer) -> OfferMatch | None:
        gtin = _offer_gtin(offer.raw_payload)
        if not gtin or gtin not in self._gtin_registry:
            return None
        evidence = self._gtin_registry[gtin]
        product_id = str(evidence["product_id"])
        variant_id = str(evidence["variant_id"])
        product = self._catalog.get(product_id)
        variant = next(
            (item for item in product.variants if item.variant_id == variant_id),
            None,
        ) if product else None
        if product is None or variant is None:
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="verified_gtin_target_missing_from_catalog",
            )
        expected_size = evidence.get("size_ml")
        if (
            not isinstance(expected_size, int)
            or offer.size_ml != expected_size
            or variant.size_ml != expected_size
        ):
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="verified_gtin_size_conflict",
                candidate_product_ids=(product.product_id,),
            )
        if offer.brand_raw and (
            normalize_brand_text(offer.brand_raw)
            != normalize_brand_text(product.brand)
        ):
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="verified_gtin_brand_conflict",
                candidate_product_ids=(product.product_id,),
            )
        if evidence.get("concentration"):
            title = normalize_identity_text(offer.raw_name)
            concentration = normalize_identity_text(str(evidence["concentration"]))
            abbreviations = {"eau de parfum": "edp", "eau de toilette": "edt"}
            short = abbreviations.get(concentration)
            if concentration not in title and not (
                short and re.search(rf"\b{re.escape(short)}\b", title)
            ):
                return OfferMatch(
                    offer=offer,
                    status=MatchStatus.UNRESOLVED,
                    reason="verified_gtin_concentration_conflict",
                    candidate_product_ids=(product.product_id,),
                )
        # Distinguish a refill pack from a refillable bottle. German
        # "nachfüllbar" (nachfullbar) means refillable, not a refill product.
        # Only explicit pack terms must be kept separate from a regular bottle.
        packaging_tokens = set(normalize_identity_text(offer.raw_name).split())
        is_refill_pack = bool(
            packaging_tokens
            & {"refill", "refills", "nachfullung", "nachfullpackung", "recharge"}
        )
        if is_refill_pack and not evidence.get("refill"):
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="verified_gtin_packaging_conflict",
                candidate_product_ids=(product.product_id,),
            )
        # Packaging and explicit concentration describe the sellable bottle,
        # not the core fragrance name. Refill-pack terms were rejected above,
        # and concentration was already checked against the verified GTIN, so
        # remove those confirmed descriptors before the exact name consistency
        # check. This accommodates retailer titles that place concentration in
        # the middle, e.g. "Liquid Brun Extrait de Parfum Limited Edition".
        identity_title = normalize_identity_text(offer.raw_name)
        verified_concentration = evidence.get("concentration")
        if verified_concentration:
            concentration_token = normalize_identity_text(str(verified_concentration))
            if concentration_token:
                identity_title = re.sub(
                    rf"\b{re.escape(concentration_token)}\b",
                    " ",
                    identity_title,
                )
        identity_title = re.sub(
            r"\b(?:\d+(?:[.,]\d+)?\s*(?:ml|cl))\b",
            " ",
            identity_title,
        )
        identity_title = re.sub(
            r"\b(?:nachfullbar|refillable|rechargeable|bottle)\b",
            " ",
            identity_title,
        )
        offer_forms = _offer_name_forms(identity_title, offer.brand_raw)
        catalog_forms = _catalog_forms([product.name, *product.aliases], product.brand)
        if not offer_forms.intersection(catalog_forms):
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="verified_gtin_name_conflict",
                candidate_product_ids=(product.product_id,),
            )
        return OfferMatch(
            offer=offer,
            status=MatchStatus.MATCHED,
            canonical_product_id=product.product_id,
            canonical_variant_id=variant.variant_id,
            confidence=Decimal("1.0"),
            reason="verified_gtin_exact_variant",
        )

    def match(self, offer: RetailerOffer) -> OfferMatch:
        gtin_match = self._match_verified_gtin(offer)
        if gtin_match is not None:
            return gtin_match
        if not _name_forms(offer.raw_name, offer.brand_raw):
            return OfferMatch(
                offer=offer,
                status=MatchStatus.UNRESOLVED,
                reason="empty_normalized_name",
            )

        offer_brand = (
            normalize_brand_text(offer.brand_raw)
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
            offer_forms = _offer_name_forms(
                offer.raw_name,
                offer.brand_raw,
            )

            for product in products:
                if (
                    offer_brand
                    and offer_brand
                    != normalize_brand_text(product.brand)
                ):
                    continue

                product_forms: set[str] = set()

                for value in [product.name, *product.aliases]:
                    product_forms.update(
                        name_forms(value, product.brand)
                    )

                # Variant aliases must retain explicit format tokens. The
                # product-level title normalizer strips generic suffixes and
                # sizes for conservative product identity; reusing those forms
                # here can make "75 ml" match a "30 ml" alias after both collapse
                # to the same base title. Match variant aliases on exact
                # normalized text (plus an explicit brand-prefix form) only.
                matched_variant_aliases = tuple(
                    variant
                    for variant in product.variants
                    if any(
                        normalize_identity_text(offer.raw_name)
                        == normalize_identity_text(value)
                        or (
                            offer_brand
                            and normalize_identity_text(offer.raw_name).startswith(
                                normalize_identity_text(product.brand) + " "
                            )
                            and normalize_identity_text(offer.raw_name)[
                                len(normalize_identity_text(product.brand)) + 1:
                            ] == normalize_identity_text(value)
                        )
                        for value in [
                            *variant.aliases,
                            *([variant.label] if variant.label else []),
                        ]
                    )
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

        # Concentration is part of fragrance identity. When the offer names
        # it explicitly and every candidate has catalogued concentration data,
        # use that evidence to distinguish EDT/EDP/etc. Never infer a missing
        # concentration or choose between duplicates sharing the same one.
        offer_concentration = _explicit_concentration(offer.raw_name)
        if (
            len(candidates) > 1
            and offer_concentration
            and all(product.concentration for product, _ in candidates)
        ):
            concentration_candidates = [
                (product, variants)
                for product, variants in candidates
                if _explicit_concentration(product.concentration)
                == offer_concentration
            ]
            if concentration_candidates and len(concentration_candidates) < len(candidates):
                candidates = concentration_candidates

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
