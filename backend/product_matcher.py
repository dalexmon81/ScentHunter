"""ScentHunter central product identity matcher.

Identity rules:
- brand prefixes in store titles are ignored for family matching;
- format/marketing words (75 ml, EDT, Eau de Toilette, Men...) are ignored;
- real variant markers are NOT ignored, so Le Beau, Le Beau Le Parfum,
  Le Beau Narcisse, etc. remain distinct catalog identities;
- the most specific catalog identity wins;
- size is kept separately as variant_id and never used to merge products.
"""
from __future__ import annotations

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

    text = " ".join(
        str(item.get(key) or "")
        for key in ("name", "title", "product_name", "size", "format")
    )
    source = _nested_source(item)
    text += " " + " ".join(
        str(source.get(key) or "") for key in ("source_name", "name")
    )
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
        aliases = data.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        formats = data.get("formats_ml") or data.get("sizes_ml") or []
        if not isinstance(formats, (list, tuple)):
            formats = [formats]
        gtins = data.get("gtins") or data.get("ean") or []
        if isinstance(gtins, str):
            gtins = [gtins]
        mpns = data.get("mpns") or data.get("mpn") or []
        if isinstance(mpns, str):
            mpns = [mpns]
        return cls(
            str(data.get("id") or data.get("catalog_id") or data.get("product_id") or "").strip(),
            str(data.get("brand") or data.get("brand_name") or "").strip(),
            str(data.get("name") or data.get("family_name") or "").strip(),
            tuple(str(x).strip() for x in aliases if str(x).strip()),
            tuple(float(x) for x in formats if str(x).strip()),
            tuple(normalize(x).replace(" ", "") for x in gtins if str(x).strip()),
            tuple(normalize(x).replace(" ", "") for x in mpns if str(x).strip()),
        )

    @property
    def normalized_brand(self) -> str:
        return normalize(self.brand)

    @property
    def identity_texts(self) -> Tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                x for x in (normalize(self.name), *(normalize(a) for a in self.aliases)) if x
            )
        )


class ProductMatcher:
    GTIN_KEYS = ("gtin", "ean", "ean13", "ean_code", "barcode", "upc")
    MPN_KEYS = ("mpn", "manufacturer_part_number", "manufacturerNumber")
    CATALOG_KEYS = ("catalog_id", "master_id", "item_group_id", "product_id")
    BRAND_KEYS = ("brand", "brand_name", "manufacturer", "maker")
    NAME_KEYS = ("name", "family_name", "title", "product_name")

    # These are presentation/format words. They may be present in a shop title
    # without changing product identity.
    FORMAT_TOKENS = {
        "eau", "de", "toilette", "parfum", "perfume", "edp", "edt",
        "extrait", "spray", "vaporisateur", "vaporisateur", "ml", "cl",
        "for", "by", "the", "men", "man", "woman", "women", "homme",
        "femme", "uomo", "donna", "natural", "oz", "fl", "ounce",
    }

    # Words/phrases that identify a real product variant. These must not be
    # discarded when deciding whether two names are the same identity.
    VARIANT_PHRASES = {
        "le parfum", "narcisse", "paradise garden", "flower edition",
        "flower", "intense", "elixir", "flame", "energy", "night",
        "night out", "rebel", "extreme", "absolu", "sport", "ice",
        "noir", "blanc", "nude", "rose", "blue", "red", "black",
        "white", "gold", "silver", "limited edition", "collector",
        "anniversary", "special edition",
    }

    def __init__(self, catalog: Iterable[Dict[str, Any] | CatalogProduct]):
        self.catalog = [
            x if isinstance(x, CatalogProduct) else CatalogProduct.from_dict(x)
            for x in catalog
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
        result["variant_id"] = (
            f"{product.catalog_id}:{resolved_size:g}"
            if resolved_size is not None
            else product.catalog_id
        )
        return result

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

    @staticmethod
    def _strip_brand_prefix(name: str, brand: str) -> str:
        if not brand:
            return name
        if name == brand:
            return ""
        prefix = brand + " "
        if name.startswith(prefix):
            return name[len(prefix):].strip()
        return name

    @classmethod
    def _identity_tokens(cls, value: str) -> List[str]:
        return [
            token for token in normalize(value).split()
            if token not in cls.FORMAT_TOKENS and not re.fullmatch(r"\d+(?:\.\d+)?", token)
        ]

    @classmethod
    def _variant_tokens(cls, value: str) -> set[str]:
        text = normalize(value)
        found: set[str] = set()
        for phrase in cls.VARIANT_PHRASES:
            phrase_n = normalize(phrase)
            if phrase_n and phrase_n in text:
                found.update(phrase_n.split())
        return found

    def _best_match(self, offer: Dict[str, Any]):
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

        best: Tuple[Optional[CatalogProduct], float, str] = (None, 0.0, "none")
        for product in self.catalog:
            score = self._text_score(brand, name, product)
            if score > best[1]:
                method = "exact_name" if score >= 0.97 else "catalog_name"
                best = (product, score, method)

        # 0.70 is deliberately conservative, but the score now understands
        # store-title noise and brand prefixes, so normal retailer names clear it.
        if best[0] is None or best[1] < 0.70:
            return None, "none", best[1]
        return best[0], best[2], best[1]

    @classmethod
    def _text_score(cls, brand: str, name: str, product: CatalogProduct) -> float:
        brand_match = bool(brand and brand == product.normalized_brand)
        offer_name = name

        # Many scrapers do not expose a separate brand field. Their title is
        # often "Jean Paul Gaultier Le Beau ...". Strip the catalog brand before
        # comparing identity words.
        offer_core = cls._strip_brand_prefix(offer_name, product.normalized_brand)
        offer_tokens = set(cls._identity_tokens(offer_core))
        if not offer_tokens:
            return 0.0

        offer_variants = cls._variant_tokens(offer_core)
        best = 0.0

        for candidate in product.identity_texts:
            candidate_core = cls._strip_brand_prefix(candidate, product.normalized_brand)
            candidate_tokens = set(cls._identity_tokens(candidate_core))
            if not candidate_tokens:
                continue

            if offer_tokens == candidate_tokens:
                base = 1.0
            else:
                inter = len(offer_tokens & candidate_tokens)
                if not inter:
                    continue
                recall = inter / len(candidate_tokens)
                precision = inter / max(1, len(offer_tokens))
                base = (2 * recall * precision / (recall + precision)) if recall + precision else 0.0

                # "Eau de Toilette 75 ml Men" is harmless title noise.
                extras = offer_tokens - candidate_tokens
                if candidate_tokens.issubset(offer_tokens) and not (extras & offer_variants):
                    base = max(base, 0.94)

            # If the offer explicitly names a real variant that the candidate
            # does not contain, do not let the generic family win.
            candidate_variants = cls._variant_tokens(candidate_core)
            if offer_variants - candidate_variants:
                base *= 0.35

            # Prefer the most specific identity when it is actually represented
            # by the offer: Le Beau Le Parfum beats the generic Le Beau.
            specificity = min(0.04, 0.01 * max(0, len(candidate_tokens) - 1))
            base = min(1.0, base + specificity)
            best = max(best, base)

        if brand_match:
            return min(1.0, 0.45 + 0.55 * best)
        # The brand may be embedded in the title rather than supplied as a field.
        # Re-check it against the raw name before applying the no-brand score.
        embedded_brand = product.normalized_brand and product.normalized_brand in offer_name
        return min(1.0, (0.50 + 0.50 * best) if embedded_brand else 0.95 * best)


def offer_key(offer: Dict[str, Any]) -> Tuple[str, str, str, str]:
    store = normalize(offer.get("store") or offer.get("source"))
    identity = normalize(offer.get("product_identity") or offer.get("catalog_id"))
    resolved_size = size_ml(offer)
    size = "" if resolved_size is None else f"{resolved_size:g}"
    url = str(offer.get("url") or "").split("#", 1)[0].split("?", 1)[0].strip().lower()
    return store, identity, size, url


def attach_matches(
    offers: Iterable[Dict[str, Any]],
    catalog: Iterable[Dict[str, Any] | CatalogProduct],
) -> List[Dict[str, Any]]:
    matcher = ProductMatcher(catalog)
    output: List[Dict[str, Any]] = []
    for offer in offers:
        if isinstance(offer, dict):
            matched = matcher.match(offer)
            if matched is not None:
                output.append(matched)
    return output
