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
    source_status: str = ""
    verification_sources: Tuple[str, ...] = ()

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
            source_status=str(data.get("source_status") or "").strip(),
            verification_sources=tuple(
                str(x).strip()
                for x in (data.get("verification_sources") or [])
                if str(x).strip()
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

    def __init__(self, catalog: Iterable[Dict[str, Any] | CatalogProduct]):
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

            if product.brand:
                brand_n = product.normalized_brand
                self._catalog_brands.add(brand_n)
                self._brand_display_by_normalized[brand_n] = product.brand

            cleaned_names: Set[str] = set()
            for value in (
                product.catalog_variant,
                product.name,
                product.family_name,
                *product.aliases,
            ):
                cleaned = self._clean_identity_name(product.brand, value)
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
                    if product.brand:
                        self._brand_by_prefix.setdefault(prefix, set()).add(
                            product.normalized_brand
                        )

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
    ) -> str:
        """
        Recover a missing/invalid retailer brand from the canonical catalog.

        The lookup is index-backed and brand-only. It never resolves a
        specific product variant.
        """
        if not raw_name:
            return ""

        # First try each catalog brand only when the title contains that brand
        # explicitly. This handles titles such as "French Avenue - Liquid Brun"
        # without scanning every catalog product.
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
        # valid variants that are not present in the catalog yet (for example
        # "Hawas Atlantis" when the catalog only knows other Hawas variants).
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
        # IMPORTANT: gender markers are identity-bearing data. They are
        # deliberately preserved here. A secondary neutral comparison may
        # remove them, but the primary catalog identity must distinguish
        # variants such as "Eros" / "Eros Pour Femme" and "9 PM" /
        # "9 PM Pour Femme".
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
        # Keep explicit gender in the canonical display identity. The
        # frontend will render gender as a separate attribute, but the
        # identity itself must never collapse male/female variants.
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

    def _exact_alias_candidates(
        self,
        offer: Dict[str, Any],
    ) -> List[CatalogProduct]:
        """Return catalog products matching the retailer identity.

        Full normalized aliases are tried first. Only when no full alias
        matches do we fall back to a cleaned identity that removes size and
        concentration. Gender is never removed from that fallback key.
        """
        brand = self._offer_brand(offer)
        raw_name = self._offer_name(offer)
        if not raw_name:
            return []

        direct_keys = {normalize(raw_name)}
        brand_tokens = normalize(brand).split()
        if brand_tokens:
            brand_stripped = normalize(raw_name)
            for token in brand_tokens:
                brand_stripped = re.sub(rf"\b{re.escape(token)}\b", " ", brand_stripped)
            brand_stripped = re.sub(r"\s+", " ", brand_stripped).strip()
            if brand_stripped:
                direct_keys.add(brand_stripped)
        source = _nested_dict(offer, "source")
        for value in (source.get("source_name"), source.get("name"), source.get("title")):
            if value:
                direct_keys.add(normalize(value))

        direct: Dict[str, CatalogProduct] = {}
        for product in self.catalog:
            if not self._brand_matches(brand, product):
                continue
            full_keys = {normalize(product.catalog_variant), normalize(product.name)}
            full_keys.update(product.normalized_aliases)
            if direct_keys & full_keys:
                direct[product.catalog_id] = product
        if direct:
            return list(direct.values())

        cleaned = self._clean_identity_name(brand, raw_name)
        if not cleaned:
            return []

        def catalog_variant_key(value: str, catalog_brand: str) -> str:
            text = normalize(value)
            for token in normalize(catalog_brand).split():
                text = re.sub(rf"\b{re.escape(token)}\b", " ", text)
            text = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|l|oz|fl oz)\b", " ", text)
            return re.sub(r"\s+", " ", text).strip()

        out: Dict[str, CatalogProduct] = {}
        for product in self.catalog:
            if not self._brand_matches(brand, product):
                continue
            keys = {
                catalog_variant_key(product.catalog_variant, product.brand),
                catalog_variant_key(product.name, product.brand),
            }
            keys.update(
                catalog_variant_key(alias, product.brand)
                for alias in product.aliases
            )
            if cleaned in keys:
                out[product.catalog_id] = product
        return list(out.values())

    def _query_matches_catalog_product(
        self,
        product: CatalogProduct,
        query: str,
    ) -> bool:
        """Check whether a catalog identity belongs to the requested query.

        A query can be a family (e.g. 'Born in Roma' or 'Boss Bottled') or a
        specific variant. Matching is token/phrase based but only against
        catalog identity fields; retailer noise cannot create a new identity.
        """
        q = normalize(query)
        if not q:
            return False
        brand_q = normalize(product.brand)
        q_tokens = [t for t in q.split() if t not in {"the"}]
        fields = [
            normalize(product.family_name),
            normalize(product.catalog_variant),
            normalize(product.name),
            *product.normalized_aliases,
        ]
        # If the query contains the catalog brand, remove it from the query
        # comparison only. Brand equality is handled separately.
        for token in normalize(product.brand).split():
            if token in q_tokens:
                q_tokens.remove(token)
        if not q_tokens:
            return True
        q_core = " ".join(q_tokens)
        return any(
            q_core == field
            or f" {q_core} " in f" {field} "
            for field in fields
            if field
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

        # First gate: full catalog alias/name identity, preserving gender and
        # concentration. This prevents neutral-core collisions.
        exact_aliases = self._exact_alias_candidates(offer)
        if exact_aliases:
            candidates = exact_aliases
        else:
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

        # Continue with generic metadata disambiguation.
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

        if not offer_gender and len(candidates) > 1:
            # A title without an explicit audience must not be promoted to a
            # gendered variant when a neutral catalog identity exists.
            neutral = [product for product in candidates if not product.gender]
            if neutral:
                candidates = neutral

        # Collapse duplicate catalog rows that describe the same identity.
        # Catalog imports can legitimately contain multiple source records for
        # one product; those records must never become multiple ScentHunter
        # identities.
        identity_rows: Dict[Tuple[str, str, str, str], CatalogProduct] = {}
        for product in candidates:
            identity_key = (
                product.normalized_brand,
                normalize(product.catalog_variant or product.name),
                normalize(product.concentration),
                normalize(product.gender),
            )
            current = identity_rows.get(identity_key)
            if current is None:
                identity_rows[identity_key] = product
                continue
            current_score = (
                len(current.verification_sources),
                1 if current.source_status == "verificato" else 0,
                len(current.aliases),
                normalize(current.catalog_id),
            )
            new_score = (
                len(product.verification_sources),
                1 if product.source_status == "verificato" else 0,
                len(product.aliases),
                normalize(product.catalog_id),
            )
            if new_score > current_score:
                identity_rows[identity_key] = product

        candidates = list(identity_rows.values())

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
        clean_name = cls._clean_identity_display(brand, name)
        parts = []
        if brand:
            parts.append(str(brand).strip())
        if clean_name:
            parts.append(clean_name)

        title = " - ".join(parts)
        if concentration:
            title = f"{title} {concentration}".strip()
        if gender:
            title = f"{title} {gender}".strip()
        return re.sub(r"\s+", " ", title).strip()

    def match(
        self,
        offer: Dict[str, Any],
        query: str = "",
    ) -> Optional[Dict[str, Any]]:
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
                product, method = self._exact_catalog_match(offer)

        if product is not None and query and not self._query_matches_catalog_product(product, query):
            # The catalog identity is real, but it does not belong to this
            # search family. Do not let a generic retailer title leak it into
            # another query.
            product = None
            method = "query_mismatch"

        if product is not None:
            canonical_brand = product.brand
            canonical_source = product.catalog_variant or product.name
            if product.gender:
                # If the catalog canonical field is neutral but an alias
                # explicitly identifies the audience, choose the alias that
                # best represents the retailer title. This avoids arbitrary
                # aliases such as "Purple Femme" winning over "Pour Femme".
                gendered_aliases = [
                    alias for alias in product.aliases
                    if normalize_gender(alias) == product.gender
                ]
                offer_gender = gender_from_offer(offer)
                if gendered_aliases and not normalize_gender(canonical_source) and offer_gender == product.gender:
                    raw_tokens = set(normalize(self._offer_name(offer)).split())
                    def alias_score(value: str) -> Tuple[int, int]:
                        tokens = set(normalize(value).split())
                        overlap = len(tokens & raw_tokens)
                        return (overlap, len(tokens))
                    canonical_source = max(gendered_aliases, key=alias_score)
            canonical_name = self._clean_identity_display(
                canonical_brand,
                canonical_source,
            ) or canonical_source
            canonical_name = re.sub(r"\bpour\s+(femme|homme)\b", lambda m: "Pour " + m.group(1).capitalize(), canonical_name, flags=re.I)
            canonical_name = re.sub(r"\bfor\s+(her|him)\b", lambda m: "For " + m.group(1).capitalize(), canonical_name, flags=re.I)
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
