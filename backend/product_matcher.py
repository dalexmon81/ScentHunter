"""ScentHunter central product identity engine.

The matcher is catalog-authoritative:
- discovery/scrapers produce raw offers;
- this module resolves a raw offer only when it maps to one catalog identity;
- unresolved/ambiguous offers are rejected, never promoted to ad-hoc products;
- size is an offer attribute, never part of identity;
- gender is preserved as identity data;
- concentration is separate and only canonicalized when known by the catalog;
- no retailer/product-specific exceptions.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stable_auto_id(*parts: Any) -> str:
    key = "::".join(normalize(p) for p in parts)
    return "SH-AUTO-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


def nested_dict(item: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def nested_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def first_value(item: Dict[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = nested_value(item.get(key))
        if value not in (None, ""):
            return str(value).strip()
    return ""


def identifier(item: Dict[str, Any], keys: Sequence[str]) -> str:
    value = first_value(item, keys)
    if not value:
        value = first_value(nested_dict(item, "identity"), keys)
    return normalize(value).replace(" ", "") if value else ""


def size_ml(item: Dict[str, Any]) -> Optional[float]:
    for key in ("size_ml", "volume_ml", "format_ml"):
        value = nested_value(item.get(key))
        if value not in (None, ""):
            try:
                return float(str(value).replace(",", "."))
            except (TypeError, ValueError):
                pass

    attrs = nested_dict(item, "attributes")
    for key in ("size_ml", "volume_ml", "format_ml"):
        value = nested_value(attrs.get(key))
        if value not in (None, ""):
            try:
                return float(str(value).replace(",", "."))
            except (TypeError, ValueError):
                pass

    text = " ".join(
        str(item.get(k) or "")
        for k in ("name", "title", "product_name", "size", "format", "volume")
    )
    text += " " + " ".join(str(v or "") for v in attrs.values())

    match = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*(ml|cl|l|oz|fl\s*oz)\b",
        text,
        re.I,
    )
    if not match:
        return None

    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower().replace(" ", "")

    if unit == "cl":
        value *= 10
    elif unit == "l":
        value *= 1000
    elif unit in ("oz", "floz"):
        value *= 29.5735

    return value


def extract_concentration(text: Any) -> str:
    value = normalize(text)

    for label, pattern in (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b|\bextrait\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
        ("Elixir", r"\belixir\b"),
    ):
        if re.search(pattern, value):
            return label

    return ""


def normalize_gender(value: Any) -> str:
    text = normalize(value)

    if re.search(r"\b(unisex|mixte|unisexe)\b", text):
        return "Unisex"

    if re.search(
        r"\b(woman|women|female|femme|donna|donne|her)\b",
        text,
    ):
        return "Donna"

    if re.search(
        r"\b(man|men|male|homme|uomo|him)\b",
        text,
    ):
        return "Uomo"

    return ""


def gender_from_offer(item: Dict[str, Any]) -> str:
    values = [
        item.get(k)
        for k in ("gender", "audience", "for_whom", "for_who", "target")
    ]

    attrs = nested_dict(item, "attributes")
    values += [
        nested_value(attrs.get(k))
        for k in ("gender", "audience", "for_whom")
    ]

    source = nested_dict(item, "source")
    values += [
        source.get(k)
        for k in ("gender", "audience", "for_whom")
    ]

    for value in values:
        gender = normalize_gender(value)
        if gender:
            return gender

    title = " ".join(
        str(item.get(k) or "")
        for k in ("name", "title", "product_name")
    )
    return normalize_gender(title)


@dataclass(frozen=True)
class CatalogProduct:
    catalog_id: str
    brand: str
    name: str
    concentration: str = ""
    gender: str = ""
    aliases: Tuple[str, ...] = ()
    formats_ml: Tuple[float, ...] = ()
    gtins: Tuple[str, ...] = ()
    mpns: Tuple[str, ...] = ()
    family_id: str = ""
    family_name: str = ""
    catalog_variant: str = ""
    source_status: str = ""
    verification_sources: Tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CatalogProduct":
        aliases = data.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]

        def identifier_values(*keys: str) -> Tuple[str, ...]:
            values: List[str] = []

            for key in keys:
                raw = data.get(key) or []
                if isinstance(raw, str):
                    raw = [raw]

                if not isinstance(raw, list):
                    continue

                for value in raw:
                    cleaned = normalize(value).replace(" ", "")
                    if cleaned and cleaned not in values:
                        values.append(cleaned)

            return tuple(values)

        formats: List[float] = []
        for value in data.get("formats_ml") or []:
            try:
                formats.append(float(value))
            except (TypeError, ValueError):
                continue

        name = str(
            data.get("name")
            or data.get("canonical_name")
            or data.get("catalog_variant")
            or data.get("family_name")
            or ""
        ).strip()

        return cls(
            catalog_id=str(
                data.get("id")
                or data.get("catalog_id")
                or ""
            ).strip(),
            brand=str(
                data.get("brand")
                or data.get("brand_name")
                or ""
            ).strip(),
            name=name,
            concentration=str(
                data.get("concentration") or ""
            ).strip(),
            gender=str(
                data.get("gender") or ""
            ).strip(),
            aliases=tuple(
                str(value).strip()
                for value in aliases
                if str(value).strip()
            ),
            formats_ml=tuple(formats),
            gtins=identifier_values("gtins", "ean"),
            mpns=identifier_values("mpns", "mpn"),
            family_id=str(
                data.get("family_id") or ""
            ).strip(),
            family_name=str(
                data.get("family_name") or ""
            ).strip(),
            catalog_variant=str(
                data.get("catalog_variant")
                or data.get("canonical_name")
                or name
            ).strip(),
            source_status=str(
                data.get("source_status") or ""
            ).strip(),
            verification_sources=tuple(
                str(value).strip()
                for value in (data.get("verification_sources") or [])
                if str(value).strip()
            ),
        )

    @property
    def normalized_brand(self) -> str:
        return normalize(self.brand)

    @property
    def normalized_name(self) -> str:
        return normalize(self.name)

    @property
    def normalized_aliases(self) -> Tuple[str, ...]:
        return tuple(
            normalize(value)
            for value in self.aliases
            if normalize(value)
        )


class ProductMatcher:
    GTIN_KEYS = (
        "gtin",
        "ean",
        "ean13",
        "ean_code",
        "barcode",
        "upc",
    )

    MPN_KEYS = (
        "mpn",
        "manufacturer_part_number",
        "manufacturerNumber",
    )

    CATALOG_KEYS = (
        "catalog_id",
        "master_id",
        "item_group_id",
        "product_id",
    )

    BRAND_KEYS = (
        "brand",
        "manufacturer",
        "maker",
    )

    NAME_KEYS = (
        "name",
        "title",
        "product_name",
    )

    NON_FRAGRANCE = (
        "body lotion",
        "body cream",
        "body milk",
        "body wash",
        "shower gel",
        "shampoo",
        "deodorant",
        "deo spray",
        "aftershave",
        "after shave",
        "body spray",
        "hair mist",
        "makeup",
        "cosmetics",
        "cosmetic",
        "skincare",
        "skin care",
        "sample",
        "tester",
        "testeur",
        "air freshener",
        "ambientador",
        "désodorisant",
        "desodorisant",
        "pochette",
        "case",
        "etui",
        "estuche",
        "miniature",
        "miniatur",
        "minispray",
    )

    SET_WORDS = (
        "gift set",
        "set regalo",
        "discovery set",
        "fragrance set",
        "perfume set",
        "parfum set",
        "coffret",
        "coffret cadeau",
        "cofanetto",
        "bundle",
        "travel set",
        "gift box",
        "mystery box",
        "duo",
        "trio",
        "set",
    )

    def __init__(
        self,
        catalog: Iterable[Dict[str, Any] | CatalogProduct],
    ):
        self.catalog = [
            item
            if isinstance(item, CatalogProduct)
            else CatalogProduct.from_dict(item)
            for item in catalog
        ]

        self._by_catalog_id: Dict[str, CatalogProduct] = {
            normalize(item.catalog_id): item
            for item in self.catalog
            if item.catalog_id
        }

        self._by_gtin: Dict[str, List[CatalogProduct]] = {}
        self._by_mpn: Dict[str, List[CatalogProduct]] = {}
        self._by_clean_name: Dict[str, List[CatalogProduct]] = {}

        for product in self.catalog:
            for value in product.gtins:
                self._by_gtin.setdefault(value, []).append(product)

            for value in product.mpns:
                self._by_mpn.setdefault(value, []).append(product)

            keys = {
                product.normalized_name,
                normalize(product.catalog_variant),
                *product.normalized_aliases,
            }

            for key in keys:
                cleaned = self._clean_identity_name(
                    product.brand,
                    key,
                )
                if cleaned:
                    self._by_clean_name.setdefault(
                        cleaned,
                        [],
                    ).append(product)

        # Multiple source rows may describe the same canonical identity.
        # Collapse those rows once, at index-build time.
        for key, rows in list(self._by_clean_name.items()):
            unique: Dict[
                Tuple[str, str, str, str],
                CatalogProduct,
            ] = {}

            for product in rows:
                identity = (
                    product.normalized_brand,
                    normalize(
                        product.catalog_variant
                        or product.name
                    ),
                    normalize(product.concentration),
                    normalize(product.gender),
                )
                unique.setdefault(identity, product)

            self._by_clean_name[key] = list(unique.values())

    @classmethod
    def _clean_identity_name(
        cls,
        brand: str,
        value: Any,
    ) -> str:
        text = normalize(value)
        if not text:
            return ""

        for token in normalize(brand).split():
            text = re.sub(
                rf"\b{re.escape(token)}\b",
                " ",
                text,
            )

        text = re.sub(
            r"\b\d{1,4}(?:[.,]\d+)?\s*"
            r"(?:ml|cl|l|oz|fl\s*oz)\b",
            " ",
            text,
        )

        text = re.sub(
            r"\b(?:eau de parfum|eau de toilette|"
            r"eau de cologne|extrait de parfum|extrait|"
            r"parfum|edp|edt|edc|spray|vaporisateur)\b",
            " ",
            text,
        )

        cleaned = re.sub(r"\s+", " ", text).strip()

        if cleaned:
            return cleaned

        # Some legitimate fragrances use the brand itself as the product
        # name. In that case the identity cannot be reduced to an empty key.
        text = normalize(value)
        text = re.sub(
            r"\b\d{1,4}(?:[.,]\d+)?\s*"
            r"(?:ml|cl|l|oz|fl\s*oz)\b",
            " ",
            text,
        )
        text = re.sub(
            r"\b(?:eau de parfum|eau de toilette|"
            r"eau de cologne|extrait de parfum|extrait|"
            r"parfum|edp|edt|edc|spray|vaporisateur)\b",
            " ",
            text,
        )

        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _identity_name_candidates(
        cls,
        product: CatalogProduct,
        raw_name: str,
    ) -> set[str]:
        """Return safe normalized identity candidates for a raw title.

        Retailers frequently append presentation metadata to the title
        (size, concentration, audience labels such as ``men``/``mixte``).
        These are not removed from the canonical identity itself. Instead,
        they are removed only for this comparison, and only when the
        resulting text exactly equals a catalog identity for the same
        product. Variant-defining phrases such as ``Pour Femme`` remain
        untouched because they are part of the catalog identity when present.
        """
        candidates = set()
        raw = cls._clean_identity_name(product.brand, raw_name)
        if raw:
            candidates.add(raw)

        # Audience labels are treated as separate evidence, never as a
        # destructive normalization rule for the canonical name.
        gender = normalize_gender(raw_name)
        if gender:
            gender_patterns = {
                "Uomo": r"\b(?:man|men|male|homme|uomo|him)\b",
                "Donna": r"\b(?:woman|women|female|femme|donna|donne|her)\b",
                "Unisex": r"\b(?:unisex|mixte|unisexe)\b",
            }
            pattern = gender_patterns.get(gender)
            if pattern:
                without_gender = re.sub(pattern, " ", raw_name, flags=re.I)
                without_gender = cls._clean_identity_name(
                    product.brand,
                    without_gender,
                )
                if without_gender:
                    candidates.add(without_gender)

        return candidates

    @classmethod
    def _is_rejected_listing(
        cls,
        offer: Dict[str, Any],
    ) -> bool:
        fields = [
            first_value(offer, cls.NAME_KEYS),
            first_value(
                offer,
                (
                    "category",
                    "product_type",
                    "type",
                    "kind",
                ),
            ),
            first_value(
                offer,
                ("description", "subtitle"),
            ),
        ]

        source = nested_dict(offer, "source")
        fields.extend(
            [
                first_value(
                    source,
                    ("source_name", "name", "title"),
                ),
                first_value(
                    source,
                    (
                        "category",
                        "product_type",
                        "type",
                    ),
                ),
            ]
        )

        text = " ".join(
            normalize(value)
            for value in fields
            if value
        )

        for phrase in cls.NON_FRAGRANCE + cls.SET_WORDS:
            phrase_normalized = normalize(phrase)
            if re.search(
                rf"\b{re.escape(phrase_normalized)}\b",
                text,
            ):
                return True

        return False

    def _offer_brand(self, offer: Dict[str, Any]) -> str:
        value = first_value(
            offer,
            self.BRAND_KEYS,
        )

        if not value:
            value = first_value(
                nested_dict(offer, "source"),
                (
                    "source_brand",
                    "brand",
                    "manufacturer",
                ),
            )

        return normalize(value)

    def _offer_name(self, offer: Dict[str, Any]) -> str:
        value = first_value(
            offer,
            self.NAME_KEYS,
        )

        if not value:
            value = first_value(
                nested_dict(offer, "source"),
                (
                    "source_name",
                    "name",
                    "title",
                ),
            )

        return value

    def _candidate_by_name(
        self,
        offer: Dict[str, Any],
    ) -> List[CatalogProduct]:
        brand = self._offer_brand(offer)
        raw_name = self._offer_name(offer)

        if not raw_name:
            return []

        # Full normalized identity first. Gender markers remain intact.
        direct_keys = {normalize(raw_name)}

        if brand:
            brand_stripped = normalize(raw_name)

            for token in brand.split():
                brand_stripped = re.sub(
                    rf"\b{re.escape(token)}\b",
                    " ",
                    brand_stripped,
                )

            brand_stripped = re.sub(
                r"\s+",
                " ",
                brand_stripped,
            ).strip()

            if brand_stripped:
                direct_keys.add(brand_stripped)

        source = nested_dict(offer, "source")

        for value in (
            source.get("source_name"),
            source.get("name"),
            source.get("title"),
        ):
            if value:
                direct_keys.add(normalize(value))

        direct_matches: Dict[str, CatalogProduct] = {}

        # A catalog can intentionally contain multiple identities sharing
        # the same canonical display name while their family/aliases
        # distinguish them (for example a base fragrance and a Pour Femme
        # variant). A shared normalized_name is therefore not sufficient
        # evidence by itself. Count those names once and require an explicit
        # variant alias/catalog_variant when the canonical name is shared.
        name_counts: Dict[str, int] = {}
        for catalog_product in self.catalog:
            key = catalog_product.normalized_name
            if key:
                name_counts[key] = name_counts.get(key, 0) + 1

        for product in self.catalog:
            if (
                brand
                and brand != product.normalized_brand
            ):
                continue

            keys = {
                normalize(product.catalog_variant),
                *product.normalized_aliases,
            }

            if (
                product.normalized_name
                and name_counts.get(product.normalized_name, 0) == 1
            ):
                keys.add(product.normalized_name)

            if direct_keys & keys:
                direct_matches[product.catalog_id] = product

        if direct_matches:
            return list(direct_matches.values())

        cleaned = self._clean_identity_name(
            brand,
            raw_name,
        )

        if cleaned:
            candidates = [
                product
                for product in self._by_clean_name.get(
                    cleaned,
                    [],
                )
                if (
                    not brand
                    or product.normalized_brand == brand
                )
            ]
            if candidates:
                return candidates

        # Some retailers do not expose the brand as a separate field and
        # instead put the brand directly in the product title.
        # In that case the previous lookup searched for
        # "french avenue liquid brun" while the catalog index correctly
        # stores "liquid brun" after removing the catalog brand.
        #
        # Resolve this generically by testing the raw name against each
        # catalog brand/name pair. This does NOT invent a brand: a candidate
        # is accepted only when removing that catalog product's own brand,
        # size and concentration leaves an exact catalog identity. If more
        # than one catalog identity survives, the normal ambiguity check in
        # _resolve() rejects it.
        if not brand:
            inferred: Dict[str, CatalogProduct] = {}

            for product in self.catalog:
                product_keys = {
                    normalize(product.catalog_variant),
                    *product.normalized_aliases,
                }

                if (
                    product.normalized_name
                    and sum(
                        1
                        for catalog_product in self.catalog
                        if catalog_product.normalized_name == product.normalized_name
                    ) == 1
                ):
                    product_keys.add(product.normalized_name)

                raw_candidates = self._identity_name_candidates(
                    product,
                    raw_name,
                )
                if not raw_candidates:
                    continue

                catalog_cleaned_keys = {
                    self._clean_identity_name(product.brand, key)
                    for key in product_keys
                }
                catalog_cleaned_keys.discard("")

                if raw_candidates & catalog_cleaned_keys:
                    inferred[product.catalog_id] = product

            if inferred:
                return list(inferred.values())

        return []

    def _identifier_match(
        self,
        offer: Dict[str, Any],
    ) -> Tuple[Optional[CatalogProduct], str]:
        gtin = identifier(
            offer,
            self.GTIN_KEYS,
        )

        if gtin:
            rows = self._by_gtin.get(gtin, [])
            if len(rows) == 1:
                return rows[0], "gtin"

        mpn = identifier(
            offer,
            self.MPN_KEYS,
        )

        if mpn:
            rows = self._by_mpn.get(mpn, [])
            if len(rows) == 1:
                return rows[0], "mpn"

        catalog_id = identifier(
            offer,
            self.CATALOG_KEYS,
        )

        if (
            catalog_id
            and catalog_id in self._by_catalog_id
        ):
            return (
                self._by_catalog_id[catalog_id],
                "catalog_id",
            )

        return None, "none"

    @staticmethod
    def _query_matches_catalog_product(
        product: CatalogProduct,
        query: str,
    ) -> bool:
        query_normalized = normalize(query)

        if not query_normalized:
            return True

        query_tokens = query_normalized.split()

        for token in product.normalized_brand.split():
            if token in query_tokens:
                query_tokens.remove(token)

        if not query_tokens:
            return True

        query_core = " ".join(query_tokens)

        fields = [
            normalize(product.family_name),
            normalize(product.catalog_variant),
            product.normalized_name,
            *product.normalized_aliases,
        ]

        return any(
            query_core == field
            or (
                f" {query_core} "
                in f" {field} "
            )
            for field in fields
            if field
        )

    def _resolve(
        self,
        offer: Dict[str, Any],
        query: str,
    ) -> Tuple[Optional[CatalogProduct], str]:
        product, method = self._identifier_match(
            offer,
        )

        if product is None:
            candidates = self._candidate_by_name(
                offer,
            )

            if not candidates:
                return None, "none"

            offer_gender = gender_from_offer(
                offer,
            )

            if offer_gender:
                gendered = [
                    item
                    for item in candidates
                    if normalize(item.gender)
                    == normalize(offer_gender)
                ]

                if gendered:
                    candidates = gendered

            offer_concentration = str(
                offer.get("concentration") or ""
            ).strip()

            if offer_concentration:
                concentration_matches = [
                    item
                    for item in candidates
                    if normalize(item.concentration)
                    == normalize(offer_concentration)
                ]

                if concentration_matches:
                    candidates = concentration_matches

            # Never guess between multiple identities.
            if len(candidates) != 1:
                return None, "ambiguous"

            product = candidates[0]
            method = "exact_name"

        if (
            query
            and not self._query_matches_catalog_product(
                product,
                query,
            )
        ):
            return None, "query_mismatch"

        return product, method

    def match(
        self,
        offer: Dict[str, Any],
        query: str = "",
    ) -> Optional[Dict[str, Any]]:
        if not isinstance(offer, dict):
            return None

        # Reject accessories, cosmetics, samples, sets and bundles before
        # identity resolution. A perfume name inside a set is not the set's
        # fragrance identity.
        if self._is_rejected_listing(offer):
            return None

        product, method = self._resolve(
            offer,
            query,
        )

        if product is None:
            # No catalog identity = no ScentHunter identity.
            # This is deliberate: the catalog is authoritative.
            return None

        result = dict(offer)

        result["result_category"] = "perfume"

        result["catalog_id"] = product.catalog_id
        result["product_identity"] = product.catalog_id
        result["variant_id"] = product.catalog_id

        result["canonical_brand"] = product.brand
        result["canonical_name"] = (
            product.catalog_variant
            or product.name
        )
        result["catalog_variant"] = (
            product.catalog_variant
            or product.name
        )

        result["family_id"] = product.family_id
        result["family_name"] = product.family_name

        result["gender"] = (
            product.gender
            or gender_from_offer(offer)
            or ""
        )

        # Once identity is certain, catalog concentration is authoritative.
        # If the catalog does not know it, do not invent one from the title.
        result["canonical_concentration"] = (
            product.concentration
        )

        if product.concentration:
            result["concentration"] = (
                product.concentration
            )

        result["match_method"] = method
        result["match_score"] = 1.0

        resolved_size = size_ml(offer)
        if resolved_size is not None:
            result["size_ml"] = resolved_size

        result["canonical_display_name"] = (
            f"{product.brand} - "
            f"{product.catalog_variant or product.name}"
        )

        if product.concentration:
            result["canonical_display_name"] += (
                f" {product.concentration}"
            )

        result["canonical_display_name"] = re.sub(
            r"\s+",
            " ",
            result["canonical_display_name"],
        ).strip()

        return result
