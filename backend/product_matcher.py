"""ScentHunter central product identity matcher.

Generic identity layer between scraper RAW offers and the API/frontend.
The matcher never contains product-specific rules. Canonical products come
from product_catalog.json through main.py.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def normalize(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def stable_auto_id(brand: Any, name: Any) -> str:
    key = f"{normalize(brand)}::{normalize(name)}"
    return "SH-AUTO-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def extract_size_ml(text: str) -> Optional[int]:
    if not text:
        return None
    text = normalize(text)
    match = re.search(
        r"(\d+(?:\.\d+)?)\s*(ml|millilitri|litri|l|oz|fl\s*oz)\b",
        text,
        re.I,
    )
    if not match:
        return None
    value = float(match.group(1))
    unit = match.group(2).lower().replace(" ", "")
    if unit in {"l", "litri"}:
        return int(value * 1000)
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


def size_ml(item: Dict[str, Any]) -> Optional[float]:
    explicit = item.get("size_ml")
    if explicit in (None, ""):
        explicit = _nested_attribute_value(item, "size_ml")
    if explicit not in (None, ""):
        try:
            return float(str(explicit).replace(",", "."))
        except (TypeError, ValueError):
            pass

    text_parts = [
        str(item.get(k) or "")
        for k in ("name", "title", "product_name", "size", "format")
    ]
    source = _nested_dict(item, "source")
    text_parts.extend(
        str(source.get(k) or "") for k in ("source_name", "name", "title")
    )
    return _extract_size_from_text(" ".join(text_parts))


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

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CatalogProduct":
        formats = []
        for value in data.get("formats_ml") or []:
            try:
                formats.append(float(value))
            except (TypeError, ValueError):
                pass

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

        return cls(
            catalog_id=str(data.get("id") or data.get("catalog_id") or "").strip(),
            brand=str(data.get("brand") or data.get("brand_name") or "").strip(),
            name=str(
                data.get("name")
                or data.get("canonical_name")
                or data.get("family_name")
                or ""
            ).strip(),
            concentration=str(data.get("concentration") or "").strip(),
            gender=str(data.get("gender") or "").strip(),
            aliases=tuple(str(x).strip() for x in aliases if str(x).strip()),
            formats_ml=tuple(formats),
            gtins=_ids("gtins", "ean"),
            mpns=_ids("mpns", "mpn"),
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

    # Commercial tokens are removed only from the derived product identity.
    # They remain available in the original offer fields.
    _IDENTITY_NOISE = {
        "eau", "de", "parfum", "parfume", "perfume", "toilette",
        "edp", "edt", "edc", "extrait", "parfum", "intense",
        "spray", "vaporisateur", "vapo",
        "homme", "uomo", "men", "man", "pour", "for",
        "femme", "donna", "women", "woman", "her",
        "ml", "milliliter", "milliliters", "oz",
    }

    _NON_IDENTITY_PHRASES = (
        "limited edition",
        "special edition",
        "anniversary edition",
        "out of stock",
        "non disponibile",
        "indisponibile",
        "agotado",
        "rupture de stock",
        "disponibile",
        "available",
        "tester",
        "air freshener",
        "ambientador",
        "désodorisant",
        "desodorisant",
        "estuche",
        "etui",
        "gift set",
        "set regalo",
        "discovery set",
        "coffret",
        "cofanetto",
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
            source = _nested_dict(offer, "source")
            value = first_value(source, ("source_brand", "brand", "manufacturer"))
        return normalize(value)

    def _offer_name(self, offer: Dict[str, Any]) -> str:
        value = first_value(offer, self.NAME_KEYS)
        if not value:
            source = _nested_dict(offer, "source")
            value = first_value(source, ("source_name", "name", "title"))
        return normalize(value)

    @staticmethod
    def _brand_matches(brand: str, product: CatalogProduct) -> bool:
        if not brand:
            return True
        return brand == product.normalized_brand

    @staticmethod
    def _token_set(value: str) -> set[str]:
        return set(normalize(value).split())

    @classmethod
    def _clean_match_name(cls, brand: str, value: str) -> str:
        text = cls._strip_brand(brand, value)
        if not text:
            return ""
        for phrase in cls._NON_IDENTITY_PHRASES:
            text = re.sub(rf"(?i)\b{re.escape(phrase)}\b", " ", text)
        text = re.sub(
            r"(?i)\b\d{1,4}(?:[.,]\d+)?\s*(?:ml|cl|l|oz|fl\.?\s*oz)\b",
            " ",
            text,
        )
        text = re.sub(
            r"(?i)\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|eau\s+de\s+cologne|"
            r"extrait(?:\s+de\s+parfum)?|parfum|edp|edt|edc|spray|vaporisateur)\b",
            " ",
            text,
        )
        text = re.sub(
            r"(?i)\b(?:pour\s+homme|pour\s+femme|for\s+men|for\s+women|"
            r"for\s+him|for\s+her|homme|uomo|men|man|femme|donna|women|woman)\b",
            " ",
            text,
        )
        return normalize(text)

    def _name_score(self, name: str, product: CatalogProduct) -> float:
        if not name:
            return 0.0

        candidates = (product.normalized_name,) + product.normalized_aliases
        best = 0.0
        name_tokens = self._token_set(name)

        for candidate in candidates:
            if not candidate:
                continue

            if name == candidate:
                return 1.0

            # A complete canonical/alias phrase occurring in the cleaned
            # retailer name is stronger than a partial token overlap.
            if re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", name):
                best = max(best, 0.97)
                continue

            candidate_tokens = self._token_set(candidate)
            if not candidate_tokens:
                continue

            overlap = len(name_tokens & candidate_tokens) / len(
                name_tokens | candidate_tokens
            )
            sequence = SequenceMatcher(None, name, candidate).ratio()
            containment = (
                len(candidate_tokens & name_tokens) / len(candidate_tokens)
            )

            score = max(
                overlap * 0.75 + sequence * 0.25,
                containment * 0.90,
            )
            best = max(best, score)

        return best

    def _best_match(
        self,
        offer: Dict[str, Any],
    ) -> Tuple[Optional[CatalogProduct], str, float]:
        gtin = identifier(offer, self.GTIN_KEYS)
        if gtin and len(self._by_gtin.get(gtin, [])) == 1:
            return self._by_gtin[gtin][0], "gtin", 1.0

        mpn = identifier(offer, self.MPN_KEYS)
        if mpn and len(self._by_mpn.get(mpn, [])) == 1:
            return self._by_mpn[mpn][0], "mpn", 0.99

        catalog_id = identifier(offer, self.CATALOG_KEYS)
        if catalog_id and catalog_id in self._by_catalog_id:
            return self._by_catalog_id[catalog_id], "catalog_id", 0.98

        brand = self._offer_brand(offer)
        raw_name = first_value(offer, self.NAME_KEYS)
        if not raw_name:
            raw_name = first_value(
                _nested_dict(offer, "source"),
                ("source_name", "name", "title"),
            )
        name = self._clean_match_name(brand, raw_name)
        if not name:
            return None, "none", 0.0

        ranked: List[Tuple[float, CatalogProduct]] = []
        for product in self.catalog:
            if not self._brand_matches(brand, product):
                continue
            score = self._name_score(name, product)
            if score > 0:
                ranked.append((score, product))

        ranked.sort(key=lambda item: item[0], reverse=True)
        if not ranked:
            return None, "none", 0.0

        score, product = ranked[0]

        # Do not let a generic one-token family absorb another product.
        if score >= 0.96:
            return product, "exact_name", score
        if score >= 0.88:
            return product, "token_score", score

        return None, "none", score

    @classmethod
    def _strip_brand(cls, brand: str, text: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return ""
        brand_raw = str(brand or "").strip()
        if brand_raw:
            pattern = rf"^\s*{re.escape(brand_raw)}\s*[-:|]?\s*"
            raw = re.sub(pattern, "", raw, flags=re.I)
        return raw.strip(" -:|")

    @classmethod
    def _derive_name_from_raw(cls, brand: str, raw_name: str) -> str:
        text = cls._strip_brand(brand, raw_name)
        if not text:
            return ""

        # Remove generic commercial/status qualifiers from the identity.
        # They remain in the original offer fields.
        for phrase in cls._NON_IDENTITY_PHRASES:
            text = re.sub(
                rf"(?i)\b{re.escape(phrase)}\b",
                " ",
                text,
            )

        text = re.sub(
            r"(?i)\b\d{1,4}(?:[.,]\d+)?\s*(?:ml|cl|l|oz|fl\.?\s*oz)\b",
            " ",
            text,
        )

        text = re.sub(
            r"(?i)\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|eau\s+de\s+cologne|"
            r"extrait(?:\s+de\s+parfum)?|parfum|edp|edt|edc|spray|vaporisateur)\b",
            " ",
            text,
        )

        text = re.sub(
            r"(?i)\b(?:pour\s+homme|pour\s+femme|for\s+men|for\s+women|"
            r"for\s+him|for\s+her|homme|uomo|men|man|femme|donna|women|woman)\b",
            " ",
            text,
        )

        text = re.sub(r"\s*[-:|/]+\s*", " ", text)
        text = re.sub(r"\s+", " ", text).strip(" -:|/")

        return text

    @classmethod
    def _derive_identity(cls, offer: Dict[str, Any]) -> Tuple[str, str]:
        brand_raw = first_value(offer, cls.BRAND_KEYS)
        if not brand_raw:
            brand_raw = first_value(
                _nested_dict(offer, "source"),
                ("source_brand", "brand", "manufacturer"),
            )

        raw_name = first_value(offer, cls.NAME_KEYS)
        if not raw_name:
            raw_name = first_value(
                _nested_dict(offer, "source"),
                ("source_name", "name", "title"),
            )

        return brand_raw.strip(), cls._derive_name_from_raw(brand_raw, raw_name)

    @classmethod
    def _clean_display_title(cls, brand: str, name: str) -> str:
        name = re.sub(r"\s+", " ", str(name or "")).strip()
        brand = re.sub(r"\s+", " ", str(brand or "")).strip()
        if not name:
            return brand
        if not brand:
            return name
        return f"{brand} - {name}"

    def match(self, offer: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        result = dict(offer)

        product, method, score = self._best_match(offer)

        if product is not None:
            canonical_brand = product.brand
            canonical_name = product.name
            result["catalog_id"] = product.catalog_id
            result["canonical_brand"] = canonical_brand
            result["canonical_name"] = canonical_name
            result["match_method"] = method
            result["match_score"] = round(score, 4)
            result["product_identity"] = product.catalog_id

            if product.concentration and not result.get("concentration"):
                result["concentration"] = product.concentration
            if product.gender and not result.get("gender"):
                result["gender"] = product.gender
        else:
            raw_identity_text = first_value(offer, self.NAME_KEYS)
            if not raw_identity_text:
                raw_identity_text = first_value(
                    _nested_dict(offer, "source"),
                    ("source_name", "name", "title"),
                )

            # A title combining multiple products is a bundle/listing, not a
            # single perfume identity. Reject it generically.
            if re.search(r"\s(?:&|\+|\band\b)\s", raw_identity_text, re.I):
                return None

            # Generic fallback: unresolved products are not discarded.
            # Identity is derived from the scraper's brand/name while all
            # commercial fields remain untouched in their original fields.
            canonical_brand, canonical_name = self._derive_identity(offer)
            if not canonical_name:
                return None

            result["catalog_id"] = result.get("catalog_id") or stable_auto_id(
                canonical_brand, canonical_name
            )
            result["canonical_brand"] = canonical_brand
            result["canonical_name"] = canonical_name
            result["match_method"] = "raw_identity"
            result["match_score"] = 0.0
            result["product_identity"] = result["catalog_id"]

        resolved_size = size_ml(offer)
        if resolved_size is not None:
            result["size_ml"] = resolved_size

        result["variant_id"] = (
            f"{result['product_identity']}:{resolved_size:g}"
            if resolved_size is not None
            else result["product_identity"]
        )

        # Stable display identity for consumers that need one field.
        result["canonical_display_name"] = self._clean_display_title(
            result.get("canonical_brand", ""),
            result.get("canonical_name", ""),
        )

        return result
