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
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


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

    _NON_IDENTITY_PHRASES = (
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

    # Only phrases that describe the CURRENT RETAILER AVAILABILITY are
    # removable. Edition/variant markers are part of product identity and
    # must never be stripped during catalog matching.
    _STATUS_PHRASES = (
        "out of stock",
        "non disponibile",
        "indisponibile",
        "agotado",
        "rupture de stock",
        "disponibile",
        "available",
    )

    def __init__(self, catalog: Iterable[Dict[str, Any] | CatalogProduct]):
        self.catalog = [
            item if isinstance(item, CatalogProduct)
            else CatalogProduct.from_dict(item)
            for item in catalog
        ]
        self._by_gtin: Dict[str, List[CatalogProduct]] = {}
        self._by_mpn: Dict[str, List[CatalogProduct]] = {}
        self._by_catalog_id: Dict[str, CatalogProduct] = {}

        for product in self.catalog:
            if product.catalog_id:
                self._by_catalog_id[normalize(product.catalog_id)] = product
            for value in product.gtins:
                self._by_gtin.setdefault(value, []).append(product)
            for value in product.mpns:
                self._by_mpn.setdefault(value, []).append(product)

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

    @staticmethod
    def _brand_matches(brand: str, product: CatalogProduct) -> bool:
        return not brand or brand == product.normalized_brand

    def _catalog_brand_hint(
        self,
        raw_name: str,
        brand: str = "",
    ) -> str:
        """
        Recover a brand only from the canonical catalog when the retailer
        did not expose one. The inference is allowed only when every matching
        catalog family/product points to the same brand.

        This is deliberately structural: it does not know any perfume or
        retailer name and never promotes a single hard-coded product to a
        special case.
        """
        if brand:
            return ""

        cleaned_offer = self._clean_identity_name("", raw_name)
        if not cleaned_offer:
            return ""

        offer_tokens = cleaned_offer.split()
        if len(offer_tokens) > 6:
            return ""

        matches: List[CatalogProduct] = []
        for product in self.catalog:
            names = [
                product.catalog_variant,
                product.name,
                product.family_name,
                *product.aliases,
            ]
            for value in names:
                candidate = self._clean_identity_name(product.brand, value)
                if not candidate:
                    continue

                # Exact family/product name.
                if cleaned_offer == candidate:
                    matches.append(product)
                    break

                # The retailer may expose a new variant whose family stem is
                # already present in the catalog, e.g. "Family New Variant".
                if candidate and cleaned_offer.startswith(candidate + " "):
                    if len(candidate.split()) >= 1:
                        matches.append(product)
                        break

                # Conversely, a retailer may expose only the beginning of a
                # cataloged variant. This is safe only when the resulting brand
                # is unique across all matching catalog entries.
                if candidate.startswith(cleaned_offer + " "):
                    if len(offer_tokens) >= 1:
                        matches.append(product)
                        break

        if not matches:
            return ""

        brands = {product.normalized_brand: product.brand for product in matches if product.brand}
        if len(brands) != 1:
            return ""
        return next(iter(brands.values()))

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
        return re.sub(r"\s+", " ", text).strip(" -:|/")

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
        cleaned = self._clean_identity_name(brand, raw_name)
        if not cleaned:
            return None, "none"

        candidates: List[Tuple[int, CatalogProduct]] = []
        for product in self.catalog:
            if not self._brand_matches(brand, product):
                continue

            for key in self._catalog_name_keys(product):
                candidate = self._clean_identity_name(product.brand, key)
                if not candidate:
                    continue

                # Exact identity only. No fuzzy score and no partial-prefix
                # acceptance. If the retailer omitted the brand field but put
                # the brand in the title, remove the catalog brand for the
                # comparison as a second, generic normalization path.
                offer_candidate = cleaned
                if not brand:
                    offer_candidate = self._clean_identity_name(product.brand, raw_name)

                if offer_candidate == candidate:
                    candidates.append((len(candidate.split()), product))
                    break

        if not candidates:
            return None, "none"

        # Generic metadata disambiguation for identical catalog names.
        offer_gender = gender_from_offer(offer)
        if offer_gender:
            filtered = [
                item for item in candidates
                if normalize(item[1].gender) == normalize(offer_gender)
            ]
            if filtered:
                candidates = filtered

        offer_concentration = (
            str(offer.get("concentration") or "").strip()
            or extract_concentration(raw_name)
        )
        if offer_concentration:
            filtered = [
                item for item in candidates
                if normalize(item[1].concentration) == normalize(offer_concentration)
            ]
            if filtered:
                candidates = filtered

        candidates.sort(
            key=lambda item: (
                item[0],
                normalize(item[1].catalog_id),
            ),
            reverse=True,
        )

        # Multiple different catalog products with the same exact normalized
        # identity are ambiguous and must not be shown.
        top_len = candidates[0][0]
        top = [
            product
            for length, product in candidates
            if length == top_len
        ]
        if len({product.catalog_id for product in top}) != 1:
            return None, "ambiguous"

        return top[0], "exact_name"

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
        parts = []
        if brand:
            parts.append(brand)
        if name:
            parts.append(name)

        title = " - ".join(parts)
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

        product, method = self._identifier_match(offer)
        if product is None:
            product, method = self._exact_catalog_match(offer)

        if product is not None:
            canonical_brand = product.brand
            canonical_name = product.catalog_variant or product.name
            concentration = (
                str(result.get("concentration") or "").strip()
                or product.concentration
                or extract_concentration(self._offer_name(offer))
            )

            result["catalog_id"] = product.catalog_id
            result["product_identity"] = product.catalog_id
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
            if not raw_brand:
                hinted_brand = self._catalog_brand_hint(
                    self._offer_name(offer),
                    "",
                )
                if hinted_brand:
                    raw_brand = hinted_brand

            # No usable product identity means the candidate is not a
            # single identifiable fragrance.
            if not raw_name:
                return None

            # Do not convert ambiguous generic text into a product.
            if len(raw_name.split()) > 12:
                return None

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
            )

        result["variant_id"] = identity
        result["product_identity"] = identity

        result["canonical_display_name"] = self._canonical_display_title(
            result.get("canonical_brand", ""),
            result.get("canonical_name", ""),
            result.get("canonical_concentration")
            or result.get("concentration", ""),
            result.get("gender") or gender_from_offer(offer),
        )

        return result
