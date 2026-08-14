"""ScentHunter central product identity matcher.

The matcher is the single identity layer between RAW scraper output and the
frontend. Scrapers may expose their source data both at top level and inside
the RAW ``source`` / ``identity`` / ``attributes`` blocks; this module accepts
both forms without adding store- or-product-specific exceptions.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def normalize(value: Any) -> str:
    value = str(value or "").strip().lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _name_for_matching(value: Any) -> str:
    """Normalize an offer name while ignoring package size for identity matching."""
    text = normalize(value)
    text = re.sub(r"\b\d{1,4}(?:[.,]\d+)?\s*(?:ml|cl)\b", " ", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def stable_auto_id(brand: Any, name: Any) -> str:
    key = f"{normalize(brand)}::{normalize(name)}"
    return "SH-AUTO-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def extract_size_ml(text: str) -> Optional[int]:
    if not text:
        return None

    text = normalize(text)
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(ml|millilitri|litri|l|oz|fl\.?\s*oz)",
        text,
        re.I,
    )
    if not match:
        return None

    value = float(match.group(1))
    unit = match.group(2).lower()

    if unit in ("l", "litri"):
        return int(value * 1000)

    if unit in ("oz", "fl. oz", "fl oz"):
        return int(value * 29.5735)

    return int(value)


def first_value(item: Dict[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _nested_source(item: Dict[str, Any]) -> Dict[str, Any]:
    value = item.get("source")
    return value if isinstance(value, dict) else {}


def _nested_identity(item: Dict[str, Any]) -> Dict[str, Any]:
    value = item.get("identity")
    return value if isinstance(value, dict) else {}


def _nested_attributes(item: Dict[str, Any]) -> Dict[str, Any]:
    value = item.get("attributes")
    return value if isinstance(value, dict) else {}


def _nested_attribute_value(item: Dict[str, Any], key: str) -> Any:
    value = _nested_attributes(item).get(key)
    if isinstance(value, dict):
        return value.get("value")
    return value


def identifier(item: Dict[str, Any], keys: Sequence[str]) -> str:
    value = first_value(item, keys)

    if not value:
        identity = _nested_identity(item)
        value = first_value(identity, keys)

    return normalize(value).replace(" ", "") if value else ""


def size_ml(item: Dict[str, Any]) -> Optional[float]:
    explicit = item.get("size_ml")

    if explicit in (None, ""):
        explicit = _nested_attribute_value(item, "size_ml")

    if explicit not in (None, ""):
        try:
            return float(str(explicit).replace(",", "."))
        except (TypeError, ValueError):
            pass

    text = " ".join(
        str(item.get(k) or "")
        for k in ("name", "title", "product_name", "size", "format")
    )

    source = _nested_source(item)
    text += " " + " ".join(
        str(source.get(k) or "")
        for k in ("source_name", "name")
    )

    match = re.search(
        r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
        re.I,
    )

    if not match:
        return None

    value = float(match.group(1).replace(",", "."))

    if match.group(2).lower() == "cl":
        value *= 10

    return value


@dataclass(frozen=True)
class CatalogProduct:
    catalog_id: str
    brand: str
    name: str
    aliases: Tuple[str, ...] = ()
    formats_ml: Tuple[float, ...] = ()
    gtins: Tuple[str, ...] = ()
    mpns: Tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(
            str(data.get("id") or data.get("catalog_id") or "").strip(),
            str(data.get("brand") or "").strip(),
            str(data.get("name") or "").strip(),
            tuple(
                str(x).strip()
                for x in (data.get("aliases") or [])
                if str(x).strip()
            ),
            tuple(
                float(x)
                for x in (data.get("formats_ml") or [])
                if str(x).strip()
            ),
            tuple(
                identifier({"v": x}, ("v",))
                for x in (data.get("gtins") or data.get("ean") or [])
                if str(x).strip()
            ),
            tuple(
                identifier({"v": x}, ("v",))
                for x in (data.get("mpns") or data.get("mpn") or [])
                if str(x).strip()
            ),
        )

    @property
    def normalized_brand(self):
        return normalize(self.brand)

    @property
    def normalized_name(self):
        return normalize(self.name)

    @property
    def normalized_aliases(self):
        return tuple(normalize(x) for x in self.aliases)


class ProductMatcher:
    GTIN_KEYS = ("gtin", "ean", "ean13", "ean_code", "barcode", "upc")
    MPN_KEYS = ("mpn", "manufacturer_part_number", "manufacturerNumber")
    CATALOG_KEYS = ("catalog_id", "master_id", "item_group_id", "product_id")
    BRAND_KEYS = ("brand", "manufacturer", "maker")
    NAME_KEYS = ("name", "title", "product_name")

    def __init__(self, catalog: Iterable[Dict[str, Any] | CatalogProduct]):
        self.catalog = [
            x if isinstance(x, CatalogProduct) else CatalogProduct.from_dict(x)
            for x in catalog
        ]

        self._by_gtin = {}
        self._by_mpn = {}
        self._by_catalog_id = {}

        for product in self.catalog:
            if product.catalog_id:
                self._by_catalog_id[normalize(product.catalog_id)] = product

            for value in product.gtins:
                self._by_gtin.setdefault(value, []).append(product)

            for value in product.mpns:
                self._by_mpn.setdefault(value, []).append(product)

    def _offer_brand(self, offer: Dict[str, Any]) -> str:
        value = first_value(offer, self.BRAND_KEYS)

        if value:
            return _name_for_matching(value)

        source = _nested_source(offer)
        value = first_value(source, ("source_brand", "brand", "manufacturer"))

        return normalize(value) if value else ""

    def _offer_name(self, offer: Dict[str, Any]) -> str:
        value = first_value(offer, self.NAME_KEYS)

        if value:
            return _name_for_matching(value)

        source = _nested_source(offer)
        value = first_value(source, ("source_name", "name", "title"))

        return _name_for_matching(value) if value else ""

    def match(self, offer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        product, method, score = self._best_match(offer)

        if product is None:
            return None

        result = dict(offer)

        # Preserve the RAW blocks exactly as supplied by the scraper while
        # exposing the canonical identity as flat fields for the API/frontend.
        result.update(
            catalog_id=product.catalog_id,
            canonical_brand=product.brand,
            canonical_name=product.name,
            match_method=method,
            match_score=round(score, 4),
            product_identity=product.catalog_id,
        )

        resolved_size = size_ml(offer)

        if resolved_size is not None:
            result["size_ml"] = resolved_size

        result["variant_id"] = (
            f"{product.catalog_id}:{resolved_size:g}"
            if resolved_size is not None
            else product.catalog_id
        )

        return result

    def _best_match(self, offer):
        gtin = identifier(offer, self.GTIN_KEYS)

        if gtin in self._by_gtin and len(self._by_gtin[gtin]) == 1:
            return self._by_gtin[gtin][0], "gtin", 1.0

        mpn = identifier(offer, self.MPN_KEYS)

        if mpn in self._by_mpn and len(self._by_mpn[mpn]) == 1:
            return self._by_mpn[mpn][0], "mpn", 0.99

        catalog_id = identifier(offer, self.CATALOG_KEYS)

        if catalog_id in self._by_catalog_id:
            return self._by_catalog_id[catalog_id], "catalog_id", 0.98

        brand = self._offer_brand(offer)
        name = self._offer_name(offer)

        if not name:
            return None, "none", 0.0

        best = (None, 0.0, "none")

        for product in self.catalog:
            score = self._text_score(brand, name, product)

            if score > best[1]:
                method = "exact_name" if score >= 0.94 else "token_score"
                best = (product, score, method)

        if best[0] is None or best[1] < 0.86:
            return None, "none", best[1]

        return best[0], best[2], best[1]

    @staticmethod
    def _text_score(brand: str, name: str, product: CatalogProduct):
        brand_score = (
            1.0
            if brand and brand == product.normalized_brand
            else 0.0
        )

        best = 0.0

        for candidate in (
            product.normalized_name,
            *product.normalized_aliases,
        ):
            if not candidate:
                continue

            if name == candidate:
                best = max(best, 1.0)
                continue

            query_tokens = set(name.split())
            candidate_tokens = set(candidate.split())

            intersection = len(query_tokens & candidate_tokens)

            recall = (
                intersection / len(candidate_tokens)
                if candidate_tokens
                else 0.0
            )

            precision = intersection / max(1, len(query_tokens))

            f_score = (
                2 * recall * precision / (recall + precision)
                if recall + precision
                else 0.0
            )

            # A shorter canonical name may match a longer offer name only
            # when the extra words are generic concentration/format words.
            # Real variants (Narcisse, Flower Edition, Paradise Garden,
            # Le Parfum, etc.) must never be swallowed by the family name.
            if candidate in name:
                extra_tokens = query_tokens - candidate_tokens
                generic_extras = {
                    "eau", "de", "parfum", "edp", "edt", "extrait",
                    "spray", "men", "man", "woman", "femme", "homme",
                    "vaporisateur", "natural"
                }
                if extra_tokens.issubset(generic_extras):
                    f_score = max(f_score, 0.92)

            best = max(best, f_score)

        return 0.45 + 0.55 * best if brand_score else 0.95 * best


def offer_key(
    offer: Dict[str, Any],
) -> Tuple[str, str, str, str]:
    store = normalize(
        offer.get("store")
        or _nested_source(offer).get("store")
        or ""
    )

    identity = normalize(
        offer.get("product_identity")
        or offer.get("catalog_id")
        or ""
    )

    resolved_size = size_ml(offer)
    size = "" if resolved_size is None else f"{resolved_size:g}"

    url = (
        str(
            offer.get("url")
            or _nested_source(offer).get("url")
            or ""
        )
        .split("#", 1)[0]
        .split("?", 1)[0]
        .strip()
        .lower()
    )

    return store, identity, size, url


def attach_matches(
    offers: Iterable[Dict[str, Any]],
    catalog: Iterable[Dict[str, Any] | CatalogProduct],
) -> List[Dict[str, Any]]:
    matcher = ProductMatcher(catalog)
    output = []

    for offer in offers:
        if isinstance(offer, dict):
            matched = matcher.match(offer)

            if matched is not None:
                output.append(matched)

    return output
