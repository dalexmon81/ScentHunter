"""ScentHunter central product identity matcher.

Generic identity layer between scraper RAW offers and the API/frontend.

Design rules:
- retailer titles remain raw source data;
- catalog matching is exact/alias based, never fuzzy across variants;
- unresolved products may keep a generic raw identity;
- non-fragrance / non-single-product listings are rejected before identity;
- variant identity never depends on bottle size;
- concentration remains a separate identity component;
- no product/store-specific rules are present here.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stable_auto_id(brand: Any, name: Any, concentration: Any = "") -> str:
    key = "::".join(
        (
            normalize(brand),
            normalize(name),
            normalize(concentration),
        )
    )
    return "SH-AUTO-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]




def normalize_gender(value: Any) -> str:
    """Normalize explicit audience/gender data without guessing from brand/product."""
    text = normalize(value)
    if not text:
        return ""
    if re.search(r"\b(unisex|mixte|unisexe)\b", text):
        return "Unisex"
    if re.search(r"\b(woman|women|female|femme|donna|donne|her|pour femme|for women)\b", text):
        return "Donna"
    if re.search(r"\b(man|men|male|homme|uomo|pour homme|for men|him)\b", text):
        return "Uomo"
    return ""


def gender_from_offer(item: Dict[str, Any]) -> str:
    """Read explicit audience data exposed by a scraper, including nested attributes."""
    values = [
        item.get("gender"),
        item.get("audience"),
        item.get("for_whom"),
        item.get("for_who"),
        item.get("target"),
        _nested_attribute_value(item, "gender"),
        _nested_attribute_value(item, "audience"),
        _nested_attribute_value(item, "for_whom"),
    ]
    source = _nested_dict(item, "source")
    values.extend((source.get("gender"), source.get("audience"), source.get("for_whom")))
    for value in values:
        gender = normalize_gender(value)
        if gender:
            return gender

    # Only explicit gender markers in the retailer title are accepted.
    title = " ".join(str(item.get(k) or "") for k in ("name", "title", "product_name"))
    return normalize_gender(title)


def extract_size_ml(text: str) -> Optional[int]:
    if not text:
        return None
    match = re.search(
        r"(\d+(?:[.,]\d+)?)\s*(ml|millilitri|cl|litri|l|oz|fl\s*oz)\b",
        str(text),
        re.I,
    )
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower().replace(" ", "")
    if unit in {"l", "litri"}:
        return int(value * 1000)
    if unit == "cl":
        return int(value * 10)
    if unit in {"oz", "floz"}:
        return int(round(value * 29.5735))
    return int(value)


def first_value(item: Dict[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _nested_dict(item: Dict[str, Any], key: str) -> Dict[str, Any]:
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def _nested_attribute_value(item: Dict[str, Any], key: str) -> Any:
    value = _nested_dict(item, "attributes").get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def identifier(item: Dict[str, Any], keys: Sequence[str]) -> str:
    value = first_value(item, keys)
    if not value:
        value = first_value(_nested_dict(item, "identity"), keys)
    return normalize(value).replace(" ", "") if value else ""


def _extract_size_from_text(text: str) -> Optional[float]:
    if not text:
        return None
    match = re.search(
        r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl|l|oz|fl\.?\s*oz)\b",
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
    elif unit in {"oz", "floz"}:
        value *= 29.5735
    return value


def size_ml(item: Dict[str, Any]) -> Optional[float]:
    explicit = item.get("size_ml")
    if explicit in (None, ""):
        explicit = _nested_attribute_value(item, "size_ml")
    if explicit not in (None, ""):
        try:
            return float(str(explicit).replace(",", "."))
        except (TypeError, ValueError):
            pass

    parts = [
        str(item.get(key) or "")
        for key in ("name", "title", "product_name", "size", "format", "volume")
    ]
    source = _nested_dict(item, "source")
    parts.extend(
        str(source.get(key) or "")
        for key in ("source_name", "name", "title")
    )
    return _extract_size_from_text(" ".join(parts))


def extract_concentration(text: Any) -> str:
    value = normalize(text)
    rules = (
        ("Extrait de Parfum", r"\bextrait(?: de)? parfum\b|\bextrait\b"),
        ("Parfum Intense", r"\bparfum intense\b"),
        ("Eau de Parfum", r"\beau de parfum\b|\bedp\b"),
        ("Eau de Toilette", r"\beau de toilette\b|\bedt\b"),
        ("Eau de Cologne", r"\beau de cologne\b|\bedc\b"),
        ("Parfum", r"\bparfum\b"),
    )
    for label, pattern in rules:
        if re.search(pattern, value, re.I):
            return label
    return ""


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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CatalogProduct":
        formats: List[float] = []
        for value in data.get("formats_ml") or []:
            try:
                formats.append(float(value))
            except (TypeError, ValueError):
                continue

        def _ids(*keys: str) -> Tuple[str, ...]:
            values: List[str] = []
            for key in keys:
                raw = data.get(key) or []
                if isinstance(raw, str):
                    raw = [raw]
                if isinstance(raw, list):
                    for value in raw:
                        cleaned = identifier({"v": value}, ("v",))
                        if cleaned and cleaned not in values:
                            values.append(cleaned)
            return tuple(values)

        aliases = data.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]

        name = str(
            data.get("name")
            or data.get("canonical_name")
            or data.get("catalog_variant")
            or data.get("family_name")
            or ""
        ).strip()

        return cls(
            catalog_id=str(data.get("id") or data.get("catalog_id") or "").strip(),
            brand=str(data.get("brand") or data.get("brand_name") or "").strip(),
            name=name,
            concentration=str(data.get("concentration") or "").strip(),
            gender=str(data.get("gender") or "").strip(),
            aliases=tuple(str(x).strip() for x in aliases if str(x).strip()),
            formats_ml=tuple(formats),
            gtins=_ids("gtins", "ean"),
            mpns=_ids("mpns", "mpn"),
            family_id=str(data.get("family_id") or "").strip(),
            family_name=str(data.get("family_name") or "").strip(),
            catalog_variant=str(
                data.get("catalog_variant")
                or data.get("canonical_name")
                or name
            ).strip(),
        )

    @property
    def normalized_brand(self) -> str:
        return normalize(self.brand)

    @property
    def normalized_name(self) -> str:
        return normalize(self.name)

    @property
    def normalized_aliases(self) -> Tuple[str, ...]:
        return tuple(normalize(x) for x in self.aliases)


class ProductMatcher:
    GTIN_KEYS = ("gtin", "ean", "ean13", "ean_code", "barcode", "upc")
    MPN_KEYS = ("mpn", "manufacturer_part_number", "manufacturerNumber")
    CATALOG_KEYS = ("catalog_id", "master_id", "item_group_id", "product_id")
    BRAND_KEYS = ("brand", "manufacturer", "maker")
    NAME_KEYS = ("name", "title", "product_name")

    _SET_PHRASES = (
        "set",
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
    )

    _NON_IDENTITY_PHRASES = (
        "mystery box",
        "gift box",
        "tester",
        "testeur",
        "sample",
        "shampoo",
        "shower gel",
        "body wash",
        "body lotion",
        "body cream",
        "body milk",
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
        "cosmetici",
        "air freshener",
        "ambientador",
        "désodorisant",
        "desodorisant",
        "estuche",
        "etui",
        "case",
        "pochette",
        "miniatur",
        "miniature",
        "minispray",
    )

    _STATUS_PHRASES = (
        "out of stock",
        "non disponibile",
        "indisponibile",
        "agotado",
        "rupture de stock",
        "disponibile",
        "available",
    )

    def __init__(
        self,
        catalog: Iterable[Dict[str, Any] | CatalogProduct],
        family_registry: Optional[Dict[str, Any] | Iterable[Dict[str, Any]]] = None,
    ):
        self.family_registry = self._normalize_family_registry(
            family_registry
        )
        self._family_brand_by_id: Dict[str, str] = {
            normalize(family.get("family_id")): str(
                family.get("brand") or ""
            ).strip()
            for family in self.family_registry
            if normalize(family.get("family_id"))
            and str(family.get("brand") or "").strip()
        }
        self._family_variant_by_alias: Dict[str, List[Dict[str, Any]]] = {}
        for family in self.family_registry:
            for variant in family.get("variants", []):
                for alias in variant.get("normalized_aliases", ()):
                    if alias:
                        self._family_variant_by_alias.setdefault(
                            alias, []
                        ).append(
                            {
                                "family_id": family.get("family_id", ""),
                                "brand": family.get("brand", ""),
                                "canonical_name": variant.get(
                                    "canonical_name", ""
                                ),
                            }
                        )

        self.catalog = [
            item if isinstance(item, CatalogProduct)
            else CatalogProduct.from_dict(item)
            for item in catalog
        ]
        self._by_gtin: Dict[str, List[CatalogProduct]] = {}
        self._by_mpn: Dict[str, List[CatalogProduct]] = {}
        self._by_catalog_id: Dict[str, CatalogProduct] = {}

        # Direct identity indexes. The previous implementation scanned the
        # whole catalog for every offer; with a large catalog this multiplied
        # scraper latency unnecessarily. These indexes keep matching
        # deterministic while reducing the identity lookup to dictionary
        # operations plus a small candidate set.
        self._by_clean_name: Dict[str, List[CatalogProduct]] = {}
        self._brand_by_prefix: Dict[str, Set[str]] = {}
        self._brand_display_by_normalized: Dict[str, str] = {}
        self._catalog_brands: Set[str] = set()

        for product in self.catalog:
            if product.catalog_id:
                self._by_catalog_id[normalize(product.catalog_id)] = product
            for value in product.gtins:
                self._by_gtin.setdefault(value, []).append(product)
            for value in product.mpns:
                self._by_mpn.setdefault(value, []).append(product)

            canonical_product_brand = self._canonical_brand_for_product(
                product
            )
            if canonical_product_brand:
                brand_n = normalize(canonical_product_brand)
                self._catalog_brands.add(brand_n)
                self._brand_display_by_normalized[brand_n] = (
                    canonical_product_brand
                )

            cleaned_names: Set[str] = set()
            for value in (
                product.catalog_variant,
                product.name,
                product.family_name,
                *product.aliases,
            ):
                cleaned = self._clean_identity_name(
                    canonical_product_brand,
                    value,
                )
                if not cleaned:
                    continue
                cleaned_names.add(cleaned)
                self._by_clean_name.setdefault(cleaned, []).append(product)

            # Every token-prefix is a possible brand-recovery key. Brand
            # recovery still requires a unique resulting brand, so this does
            # not resolve a variant merely because it shares a prefix.
            for cleaned in cleaned_names:
                tokens = cleaned.split()
                for end in range(1, len(tokens) + 1):
                    prefix = " ".join(tokens[:end])
                    if canonical_product_brand:
                        self._brand_by_prefix.setdefault(prefix, set()).add(
                            normalize(canonical_product_brand)
                        )

    @staticmethod
    def _normalize_family_registry(
        registry: Optional[
            Dict[str, Any] | Iterable[Dict[str, Any]]
        ],
    ) -> List[Dict[str, Any]]:
        if registry is None:
            path = Path(__file__).resolve().with_name(
                "family_registry.json"
            )
            try:
                if path.exists():
                    registry = json.loads(
                        path.read_text(encoding="utf-8")
                    )
            except Exception:
                registry = None

        if isinstance(registry, dict):
            families = registry.get("families") or []
        else:
            families = list(registry or [])

        output: List[Dict[str, Any]] = []
        for family in families:
            if not isinstance(family, dict):
                continue

            family_id = str(
                family.get("family_id") or ""
            ).strip()
            brand = str(
                family.get("brand") or ""
            ).strip()
            query_aliases = family.get("query_aliases") or family.get(
                "search_aliases"
            ) or []
            if isinstance(query_aliases, str):
                query_aliases = [query_aliases]

            raw_products = (
                family.get("products")
                or family.get("allowed_variants")
                or family.get("variants")
                or []
            )
            if not isinstance(raw_products, list):
                continue

            variants: List[Dict[str, Any]] = []
            for variant in raw_products:
                if not isinstance(variant, dict):
                    continue

                canonical = str(
                    variant.get("canonical_name")
                    or variant.get("name")
                    or ""
                ).strip()
                if not canonical:
                    continue

                aliases = variant.get("aliases") or []
                if isinstance(aliases, str):
                    aliases = [aliases]

                values: List[str] = []
                for value in [canonical, *aliases]:
                    value = str(value or "").strip()
                    if value and value not in values:
                        values.append(value)

                variants.append(
                    {
                        "canonical_name": canonical,
                        "normalized_aliases": tuple(
                            normalize(value)
                            for value in values
                            if normalize(value)
                        ),
                    }
                )

            if family_id and variants:
                output.append(
                    {
                        "family_id": family_id,
                        "brand": brand,
                        "query_aliases": tuple(
                            normalize(value)
                            for value in query_aliases
                            if normalize(value)
                        ),
                        "variants": variants,
                    }
                )

        return output

    def _canonical_brand_for_product(
        self,
        product: CatalogProduct,
    ) -> str:
        if product.brand:
            return product.brand

        family_brand = self._family_brand_by_id.get(
            normalize(product.family_id),
            "",
        )
        return family_brand

    @staticmethod
    def _family_brand_matches(
        offer_brand: str,
        family_brand: str,
    ) -> bool:
        if not offer_brand or not family_brand:
            return True
        return normalize(offer_brand) == normalize(family_brand)

    @staticmethod
    def _clean_family_candidate(
        value: Any,
        brand: str = "",
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
            r"eau de cologne|eau fraiche|extrait de parfum|"
            r"extrait|parfum|edp|edt|edc|spray|vaporisateur)\b",
            " ",
            text,
        )

        text = re.sub(
            r"\s+",
            " ",
            text,
        ).strip()

        return text

    def _family_variant_for_offer(
        self,
        offer: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        raw_name = self._offer_name(offer)
        if not raw_name:
            return None

        offer_brand = self._offer_brand(offer)

        # Exact alias matching is the authoritative family route.
        candidate = normalize(raw_name)
        matches: List[Dict[str, Any]] = []

        for family in self.family_registry:
            family_brand = str(
                family.get("brand") or ""
            ).strip()

            if not self._family_brand_matches(
                offer_brand,
                family_brand,
            ):
                continue

            family_aliases = family.get("query_aliases", ())
            family_anchor = (
                bool(offer_brand and family_brand)
                and normalize(offer_brand) == normalize(family_brand)
            ) or any(
                alias and (
                    candidate == alias
                    or f" {alias} " in f" {candidate} "
                )
                for alias in family_aliases
            )
            if not family_anchor:
                continue

            for variant in family.get("variants", []):
                for alias in variant.get("normalized_aliases", ()):
                    if candidate == alias:
                        matches.append(
                            {
                                "family_id": family.get("family_id", ""),
                                "brand": family_brand,
                                "canonical_name": variant.get(
                                    "canonical_name", ""
                                ),
                            }
                        )

        if len(matches) == 1:
            return matches[0]

        # Retailer titles commonly add size/concentration/commercial
        # descriptors around an exact family alias. Strip only those generic
        # descriptors and retry; never strip variant/audience words here.
        cleaned = self._clean_family_candidate(
            raw_name,
            "",
        )
        if not cleaned:
            return None

        for family in self.family_registry:
            family_brand = str(
                family.get("brand") or ""
            ).strip()

            if not self._family_brand_matches(
                offer_brand,
                family_brand,
            ):
                continue

            family_aliases = family.get("query_aliases", ())
            family_anchor = (
                bool(offer_brand and family_brand)
                and normalize(offer_brand) == normalize(family_brand)
            ) or any(
                alias and (
                    alias in f" {cleaned} "
                    or alias in f" {normalize(raw_name)} "
                )
                for alias in family_aliases
            )
            if not family_anchor:
                continue

            for variant in family.get("variants", []):
                family_cleaned = self._clean_family_candidate(
                    raw_name,
                    family_brand,
                )
                for alias in variant.get("normalized_aliases", ()):
                    if family_cleaned == alias or cleaned == alias:
                        matches.append(
                            {
                                "family_id": family.get("family_id", ""),
                                "brand": family_brand,
                                "canonical_name": variant.get(
                                    "canonical_name", ""
                                ),
                            }
                        )

        unique = {
            (
                normalize(item.get("family_id")),
                normalize(item.get("canonical_name")),
            ): item
            for item in matches
        }
        return next(iter(unique.values())) if len(unique) == 1 else None

    def _match_family_registry(
        self,
        offer: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        variant = self._family_variant_for_offer(offer)
        if variant is None:
            return None

        family_id = str(
            variant.get("family_id") or ""
        ).strip()
        canonical_name = str(
            variant.get("canonical_name") or ""
        ).strip()
        canonical_brand = str(
            variant.get("brand") or ""
        ).strip()

        if not canonical_name:
            return None

        # Prefer an existing catalog identity for the family+variant.
        catalog_id = ""
        family_name = ""
        for product in self.catalog:
            if normalize(product.family_id) != normalize(family_id):
                continue
            product_name = product.catalog_variant or product.name
            if normalize(product_name) == normalize(canonical_name):
                catalog_id = product.catalog_id
                family_name = product.family_name
                if not canonical_brand:
                    canonical_brand = self._canonical_brand_for_product(
                        product
                    )
                break

        if not catalog_id:
            catalog_id = stable_auto_id(
                canonical_brand,
                f"{family_id}::{canonical_name}",
            )

        result = dict(offer)
        result["catalog_id"] = catalog_id
        result["product_identity"] = catalog_id
        result["brand"] = canonical_brand
        result["canonical_brand"] = canonical_brand
        result["canonical_name"] = canonical_name
        result["catalog_variant"] = canonical_name
        result["family_id"] = family_id
        result["family_name"] = family_name or canonical_name
        result["canonical_concentration"] = (
            str(result.get("concentration") or "").strip()
            or extract_concentration(self._offer_name(offer))
        )
        result["gender"] = (
            gender_from_offer(offer)
            or ""
        )
        result["match_method"] = "family_registry_alias"
        result["match_score"] = 1.0
        return result

    def _offer_brand(self, offer: Dict[str, Any]) -> str:
        value = first_value(offer, self.BRAND_KEYS)
        if not value:
            value = first_value(
                _nested_dict(offer, "source"),
                ("source_brand", "brand", "manufacturer"),
            )
        return normalize(value)

    def _offer_name(self, offer: Dict[str, Any]) -> str:
        value = first_value(offer, self.NAME_KEYS)
        if not value:
            value = first_value(
                _nested_dict(offer, "source"),
                ("source_name", "name", "title"),
            )
        return value

    def _brand_matches(
        self,
        brand: str,
        product: CatalogProduct,
    ) -> bool:
        canonical_brand = normalize(
            self._canonical_brand_for_product(product)
        )
        return not brand or brand == canonical_brand

    def _catalog_brand_hint(
        self,
        raw_name: str,
    ) -> str:
        """
        Recover a missing/invalid retailer brand from the canonical catalog.

        The lookup is index-backed and brand-only. It never resolves a
        specific product variant.
        """
        if not raw_name:
            return ""

        # First try each catalog brand only when the title contains that brand
        # explicitly. This handles retailer titles where the brand is a
        # known catalog brand followed by the product name.
        raw_normalized = normalize(raw_name)
        for brand_n, brand_display in self._brand_display_by_normalized.items():
            brand_tokens = brand_n.split()
            if brand_tokens and all(token in raw_normalized.split() for token in brand_tokens):
                cleaned = self._clean_identity_name(brand_display, raw_name)
                if cleaned in self._brand_by_prefix:
                    brands = self._brand_by_prefix[cleaned]
                    if len(brands) == 1:
                        return self._brand_display_by_normalized[next(iter(brands))]

        # Then use the normalized title itself. The important part here is
        # that brand recovery must work from a *known catalog prefix*, not
        # only from a complete catalog product name. Retailers often publish
        # valid variants that are not present in the catalog yet. The shared
        # family/brand prefix remains safe evidence only when unique.
        # In that case the shared family/brand prefix is still safe evidence
        # when it maps to one unique brand.
        cleaned = self._clean_identity_name("", raw_name)
        if not cleaned:
            return ""

        tokens = cleaned.split()
        for end in range(len(tokens), 0, -1):
            prefix = " ".join(tokens[:end])
            brands = self._brand_by_prefix.get(prefix, set())
            if len(brands) == 1:
                return self._brand_display_by_normalized[next(iter(brands))]
            if len(brands) > 1:
                # A non-unique prefix is not enough evidence to infer a brand.
                # Keep looking at shorter prefixes only if they can provide a
                # uniquely attributable family/brand boundary.
                continue

        return ""

    @classmethod
    def _clean_identity_name(cls, brand: str, value: Any) -> str:
        text = normalize(value)
        if not text:
            return ""

        # Retailer titles may place the brand before or after the product.
        # Remove only exact brand tokens; variant words remain untouched.
        brand_tokens = normalize(brand).split()
        for token in brand_tokens:
            text = re.sub(rf"\b{re.escape(token)}\b", " ", text)

        for phrase in cls._NON_IDENTITY_PHRASES + cls._STATUS_PHRASES:
            text = re.sub(rf"\b{re.escape(normalize(phrase))}\b", " ", text)

        text = re.sub(
            r"\b\d{1,4}(?:[.,]\d+)?\s*(?:ml|cl|l|oz|fl\s*oz)\b",
            " ",
            text,
        )
        text = re.sub(
            r"\b(?:eau de parfum|eau de toilette|eau de cologne|"
            r"extrait de parfum|extrait|parfum|edp|edt|edc|"
            r"spray|vaporisateur)\b",
            " ",
            text,
        )
        text = re.sub(
            r"\b(?:pour homme|pour femme|pour hommes|pour femmes|"
            r"for men|for women|for him|for her|"
            r"homme|uomo|men|man|femme|donna|women|woman|"
            r"unisex|mixte|unisexe)\b",
            " ",
            text,
        )
        text = re.sub(r"\(\s*\)", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _clean_identity_display(cls, brand: str, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""

        for token in normalize(brand).split():
            text = re.sub(rf"\b{re.escape(token)}\b", " ", text, flags=re.I)

        for phrase in cls._NON_IDENTITY_PHRASES + cls._STATUS_PHRASES:
            text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text, flags=re.I)

        text = re.sub(
            r"\b\d{1,4}(?:[.,]\d+)?\s*(?:ml|cl|l|oz|fl\s*oz)\b",
            " ",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|"
            r"eau\s+de\s+cologne|extrait(?:\s+de\s+parfum)?|"
            r"parfum|edp|edt|edc|spray|vaporisateur)\b",
            " ",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"\b(?:pour\s+homme|pour\s+femme|pour\s+hommes|"
            r"pour\s+femmes|for\s+men|for\s+women|for\s+him|"
            r"for\s+her|homme|uomo|men|man|femme|donna|women|woman|"
            r"unisex|mixte|unisexe)\b",
            " ",
            text,
            flags=re.I,
        )
        text = re.sub(r"\(\s*\)", " ", text)
        return re.sub(r"\s+", " ", text).strip(" -:|/")

    @classmethod
    def _is_set(cls, offer: Dict[str, Any]) -> bool:
        fields = [
            first_value(offer, cls.NAME_KEYS),
            first_value(offer, ("category", "product_type", "type", "kind")),
        ]
        source = _nested_dict(offer, "source")
        fields.extend((
            first_value(source, ("source_name", "name", "title")),
            first_value(source, ("category", "product_type", "type")),
        ))
        for raw in fields:
            text = normalize(raw)
            if any(re.search(rf"\b{re.escape(normalize(phrase))}\b", text) for phrase in cls._SET_PHRASES):
                return True
        return False

    @classmethod
    def _is_non_fragrance(cls, offer: Dict[str, Any]) -> bool:
        fields = [
            first_value(offer, cls.NAME_KEYS),
            first_value(offer, ("category", "product_type", "type", "kind")),
            first_value(offer, ("description", "subtitle")),
        ]
        source = _nested_dict(offer, "source")
        fields.extend(
            [
                first_value(source, ("source_name", "name", "title")),
                first_value(source, ("category", "product_type", "type")),
            ]
        )

        for raw in fields:
            text = normalize(raw)
            if not text:
                continue
            for phrase in cls._NON_IDENTITY_PHRASES:
                phrase_n = normalize(phrase)
                if re.search(rf"\b{re.escape(phrase_n)}\b", text):
                    return True
        return False

    @classmethod
    def _catalog_name_keys(cls, product: CatalogProduct) -> Tuple[str, ...]:
        values = [
            product.catalog_variant,
            product.name,
            *product.aliases,
        ]
        return tuple(
            key for key in (normalize(value) for value in values)
            if key
        )

    def _exact_catalog_match(
        self,
        offer: Dict[str, Any],
    ) -> Tuple[Optional[CatalogProduct], str]:
        brand = self._offer_brand(offer)
        raw_name = self._offer_name(offer)

        effective_brand = brand
        if not effective_brand or effective_brand not in self._catalog_brands:
            hinted_brand = self._catalog_brand_hint(raw_name)
            if hinted_brand:
                effective_brand = normalize(hinted_brand)

        cleaned = self._clean_identity_name(effective_brand, raw_name)
        if not cleaned:
            return None, "none"

        candidates = [
            product
            for product in self._by_clean_name.get(cleaned, [])
            if self._brand_matches(effective_brand, product)
        ]
        if not candidates:
            return None, "none"

        # Generic metadata disambiguation for identical catalog names.
        offer_gender = gender_from_offer(offer)
        if offer_gender:
            filtered = [
                product
                for product in candidates
                if normalize(product.gender) == normalize(offer_gender)
            ]
            if filtered:
                candidates = filtered

        offer_concentration = (
            str(offer.get("concentration") or "").strip()
            or extract_concentration(raw_name)
        )
        if offer_concentration:
            filtered = [
                product
                for product in candidates
                if normalize(product.concentration) == normalize(offer_concentration)
            ]
            if filtered:
                candidates = filtered

        # De-duplicate the same catalog product reached through multiple aliases.
        unique: Dict[str, CatalogProduct] = {}
        for product in candidates:
            unique[product.catalog_id] = product
        candidates = list(unique.values())

        candidates.sort(
            key=lambda product: (
                len(product.catalog_variant.split()),
                normalize(product.catalog_id),
            ),
            reverse=True,
        )

        if len(candidates) != 1:
            return None, "ambiguous"

        return candidates[0], "exact_name"

    def _identifier_match(
        self,
        offer: Dict[str, Any],
    ) -> Tuple[Optional[CatalogProduct], str]:
        gtin = identifier(offer, self.GTIN_KEYS)
        if gtin and len(self._by_gtin.get(gtin, [])) == 1:
            return self._by_gtin[gtin][0], "gtin"

        mpn = identifier(offer, self.MPN_KEYS)
        if mpn and len(self._by_mpn.get(mpn, [])) == 1:
            return self._by_mpn[mpn][0], "mpn"

        catalog_id = identifier(offer, self.CATALOG_KEYS)
        if catalog_id and catalog_id in self._by_catalog_id:
            return self._by_catalog_id[catalog_id], "catalog_id"

        return None, "none"

    @classmethod
    def _derive_identity(
        cls,
        offer: Dict[str, Any],
    ) -> Tuple[str, str, str]:
        brand = first_value(offer, cls.BRAND_KEYS)
        if not brand:
            brand = first_value(
                _nested_dict(offer, "source"),
                ("source_brand", "brand", "manufacturer"),
            )

        raw_name = first_value(offer, cls.NAME_KEYS)
        if not raw_name:
            raw_name = first_value(
                _nested_dict(offer, "source"),
                ("source_name", "name", "title"),
            )

        cleaned = cls._clean_identity_name(brand, raw_name)
        display_name = cls._clean_identity_display(brand, raw_name)
        concentration = (
            str(offer.get("concentration") or "").strip()
            or extract_concentration(raw_name)
        )

        return (
            str(brand or "").strip(),
            display_name or cleaned,
            concentration,
        )

    @classmethod
    def _canonical_display_title(
        cls,
        brand: str,
        name: str,
        concentration: str,
        gender: str = "",
    ) -> str:
        # Brand, variante, concentrazione e genere sono campi distinti.
        # Il genere non deve mai restare duplicato dentro il nome della
        # variante: viene visualizzato una sola volta dopo la concentrazione.
        # The canonical variant name is authoritative.  In particular,
        # audience words such as "For Him" / "For Her" may be part of the
        # actual variant identity and must never be stripped at display time.
        clean_name = str(name or "").strip()
        for token in normalize(brand).split():
            clean_name = re.sub(
                rf"\b{re.escape(token)}\b",
                " ",
                clean_name,
                flags=re.I,
            )
        clean_name = re.sub(r"\(\s*\)", " ", clean_name)
        clean_name = re.sub(r"\s+", " ", clean_name).strip(" -:|/")

        parts = []
        if brand:
            parts.append(str(brand).strip())
        if clean_name:
            parts.append(clean_name)

        title = "-".join(parts)
        if concentration:
            title = f"{title} {concentration}".strip()
        if gender:
            title = f"{title} {gender}".strip()
        return re.sub(r"\s+", " ", title).strip()

    def match(self, offer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not isinstance(offer, dict):
            return None

        if self._is_non_fragrance(offer):
            return None

        result = dict(offer)
        is_set = self._is_set(offer)
        result["result_category"] = "set" if is_set else "perfume"

        # A set/coffret is a valid ScentHunter result, but it is not the same
        # catalog identity as the perfume(s) contained in the set. Keep its
        # own retailer identity instead of collapsing it onto the perfume.
        if is_set:
            product, method = None, "set_identity"
        else:
            product, method = self._identifier_match(offer)
            if product is None:
                family_result = self._match_family_registry(offer)
                if family_result is not None:
                    result.update(family_result)
                    result["result_category"] = (
                        "set" if is_set else "perfume"
                    )
                    result["canonical_display_name"] = (
                        self._canonical_display_title(
                            result.get("canonical_brand", ""),
                            result.get("canonical_name", ""),
                            result.get("canonical_concentration")
                            or result.get("concentration", ""),
                            "",
                        )
                    )
                    return result
                product, method = self._exact_catalog_match(offer)

        if product is not None:
            canonical_brand = self._canonical_brand_for_product(
                product
            )
            canonical_name = self._clean_identity_display(
                canonical_brand,
                product.catalog_variant or product.name,
            ) or (product.catalog_variant or product.name)
            concentration = (
                str(result.get("concentration") or "").strip()
                or product.concentration
                or extract_concentration(self._offer_name(offer))
            )

            result["catalog_id"] = product.catalog_id
            result["product_identity"] = product.catalog_id
            # Once the catalog has resolved the product, its canonical brand
            # is the authoritative brand for the normalized result. Keep the
            # raw retailer fields intact only when no canonical identity exists.
            result["brand"] = canonical_brand
            result["canonical_brand"] = canonical_brand
            result["canonical_name"] = canonical_name
            result["catalog_variant"] = canonical_name
            result["family_id"] = product.family_id
            result["family_name"] = product.family_name
            result["canonical_concentration"] = concentration
            result["gender"] = (
                product.gender
                or gender_from_offer(offer)
                or ""
            )
            result["match_method"] = method
            result["match_score"] = 1.0

            if concentration and not result.get("concentration"):
                result["concentration"] = concentration
            if product.gender and not result.get("gender"):
                result["gender"] = product.gender

        else:
            raw_brand, raw_name, concentration = self._derive_identity(offer)

            if not raw_brand or normalize(raw_brand) not in self._catalog_brands:
                hinted_brand = self._catalog_brand_hint(
                    self._offer_name(offer),
                )
                if hinted_brand:
                    raw_brand = hinted_brand
                    raw_name = self._clean_identity_display(
                        hinted_brand,
                        self._offer_name(offer),
                    ) or raw_name

            # No usable product identity means the candidate is not a
            # single identifiable fragrance.
            if not raw_name:
                return None

            # Do not convert ambiguous generic text into a product.
            if len(raw_name.split()) > 12:
                return None

            # If brand recovery produced a canonical catalog brand, propagate
            # it to the normalized brand field as well. This keeps downstream
            # display and identity consumers consistent without any product-
            # specific rule.
            if raw_brand:
                result["brand"] = raw_brand
            result["canonical_brand"] = raw_brand
            result["canonical_name"] = raw_name
            result["catalog_variant"] = raw_name
            result["family_id"] = ""
            result["family_name"] = ""
            result["canonical_concentration"] = concentration
            result["gender"] = gender_from_offer(offer)
            result["match_method"] = "raw_identity"
            result["match_score"] = 0.0

            if concentration and not result.get("concentration"):
                result["concentration"] = concentration

            result["catalog_id"] = result.get("catalog_id") or stable_auto_id(
                raw_brand,
                raw_name,
                concentration,
            )
            result["product_identity"] = result["catalog_id"]

        resolved_size = size_ml(offer)
        if resolved_size is not None:
            result["size_ml"] = resolved_size

        # Product identity is variant + concentration, never bottle size.
        if product is not None:
            identity = product.catalog_id
        else:
            identity = stable_auto_id(
                result.get("canonical_brand", ""),
                result.get("catalog_variant") or result.get("canonical_name", ""),
                result.get("canonical_concentration")
                or result.get("concentration", ""),
            )

        result["variant_id"] = identity
        result["product_identity"] = identity

        result["canonical_display_name"] = self._canonical_display_title(
            result.get("canonical_brand", ""),
            result.get("canonical_name", ""),
            result.get("canonical_concentration")
            or result.get("concentration", ""),
            "",
        )

        return result
