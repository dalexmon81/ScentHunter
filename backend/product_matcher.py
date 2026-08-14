"""ScentHunter central product identity matcher."""
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
    text = normalize(value)
    text = re.sub(r"\b\d{1,4}(?:[.,]\d+)?\s*(?:ml|cl)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_size_ml(text: str) -> Optional[int]:
    if not text:
        return None
    text = normalize(text)
    match = re.search(r"(\d+(?:\.\d+)?)\s*(ml|millilitri|litri|l|oz|fl\.?\s*oz)", text, re.I)
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
    return value.get("value") if isinstance(value, dict) else value


def identifier(item: Dict[str, Any], keys: Sequence[str]) -> str:
    value = first_value(item, keys)
    if not value:
        value = first_value(_nested_identity(item), keys)
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

    text = " ".join(str(item.get(key) or "") for key in ("name", "title", "product_name", "size", "format"))
    source = _nested_source(item)
    text += " " + " ".join(str(source.get(key) or "") for key in ("source_name", "name"))
    match = re.search(r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl)\b", text, re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return value * 10 if match.group(2).lower() == "cl" else value


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
            str(data.get("id") or data.get("catalog_id") or data.get("product_id") or "").strip(),
            str(data.get("brand") or data.get("brand_name") or "").strip(),
            str(data.get("name") or data.get("family_name") or "").strip(),
            tuple(str(x).strip() for x in (data.get("aliases") or []) if str(x).strip()),
            tuple(float(x) for x in (data.get("formats_ml") or data.get("sizes_ml") or []) if str(x).strip()),
            tuple(normalize(x).replace(" ", "") for x in (data.get("gtins") or data.get("ean") or []) if str(x).strip()),
            tuple(normalize(x).replace(" ", "") for x in (data.get("mpns") or data.get("mpn") or []) if str(x).strip()),
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

    @property
    def identity_texts(self):
        return tuple(dict.fromkeys((self.normalized_name, *self.normalized_aliases)))


class ProductMatcher:
    GTIN_KEYS = ("gtin", "ean", "ean13", "ean_code", "barcode", "upc")
    MPN_KEYS = ("mpn", "manufacturer_part_number", "manufacturerNumber")
    CATALOG_KEYS = ("catalog_id", "master_id", "item_group_id", "product_id")
    BRAND_KEYS = ("brand", "brand_name", "manufacturer", "maker")
    NAME_KEYS = ("name", "family_name", "title", "product_name")

    def __init__(self, catalog: Iterable[Dict[str, Any] | CatalogProduct]):
        self.catalog = [x if isinstance(x, CatalogProduct) else CatalogProduct.from_dict(x) for x in catalog]
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
        if not value:
            value = first_value(_nested_source(offer), ("source_brand", "brand", "manufacturer"))
        return _name_for_matching(value)

    def _offer_name(self, offer: Dict[str, Any]) -> str:
        value = first_value(offer, self.NAME_KEYS)
        if not value:
            value = first_value(_nested_source(offer), ("source_name", "name", "title"))
        return _name_for_matching(value)

    def match(self, offer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        product, method, score = self._best_match(offer)
        if product is None:
            return None

        result = dict(offer)
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
        result["variant_id"] = f"{product.catalog_id}:{resolved_size:g}" if resolved_size is not None else product.catalog_id
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
                best = (product, score, "exact_name" if score >= 0.94 else "token_score")

        if best[0] is None or best[1] < 0.70:
            return None, "none", best[1]
        return best[0], best[2], best[1]

    @staticmethod
    def _text_score(brand: str, name: str, product: CatalogProduct):
        brand_score = 1.0 if brand and brand == product.normalized_brand else 0.0
        best = 0.0
        generic_tokens = {
            "eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray",
            "men", "man", "woman", "femme", "homme", "vaporisateur", "natural",
            "ml", "for", "by",
        }

        for candidate in product.identity_texts:
            if not candidate:
                continue
            if name == candidate:
                best = max(best, 1.0)
                continue

            name_tokens = set(name.split())
            candidate_tokens = set(candidate.split())
            intersection = len(name_tokens & candidate_tokens)
            if not intersection:
                continue

            recall = intersection / len(candidate_tokens)
            precision = intersection / max(1, len(name_tokens))
            f_score = 2 * recall * precision / (recall + precision) if recall + precision else 0.0

            extra_tokens = name_tokens - candidate_tokens
            if candidate in name and extra_tokens.issubset(generic_tokens):
                f_score = max(f_score, 0.92)

            best = max(best, f_score)

        return (0.45 + 0.55 * best) if brand_score else (0.95 * best)


def attach_matches(offers: Iterable[Dict[str, Any]], catalog: Iterable[Dict[str, Any] | CatalogProduct]) -> List[Dict[str, Any]]:
    matcher = ProductMatcher(catalog)
    output = []
    for offer in offers:
        if isinstance(offer, dict):
            matched = matcher.match(offer)
            if matched is not None:
                output.append(matched)
    return output
