"""ScentHunter central product identity matcher.

This module is the single identity layer between RAW scraper output and the
frontend.  Scrapers expose source data; this module resolves that data to a
canonical catalog/family identity without store-specific or product-specific
exceptions.
"""
from __future__ import annotations

import hashlib
import re
import time
from collections import Counter
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


def catalog_norm(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def catalog_clean_text(value: Any) -> str:
    """Remove only commercial descriptors, never gender/variant markers."""
    text = catalog_norm(value)

    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
        " ",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|"
        r"eau\s+de\s+cologne|eau\s+fraiche|"
        r"extrait\s+de\s+parfum|edp|edt|edc|parfum|perfume|spray)\b",
        " ",
        text,
        flags=re.I,
    )

    return re.sub(r"\s+", " ", text).strip()


def catalog_variant_key(value: Any) -> str:
    return catalog_clean_text(value)


def stable_auto_id(brand: Any, name: Any) -> str:
    key = f"{normalize(brand)}::{normalize(name)}"
    return "SH-AUTO-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


def stable_family_id(family_id: Any, canonical_name: Any) -> str:
    key = f"{normalize(family_id)}::{normalize(canonical_name)}"
    return "SH-FAMILY-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]


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
        str(item.get(k) or "")
        for k in ("name", "title", "product_name", "canonical_name", "size", "format")
    )
    source = _nested_source(item)
    text += " " + " ".join(
        str(source.get(k) or "") for k in ("source_name", "name", "title")
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
    family_id: str = ""
    family_name: str = ""
    catalog_variant: str = ""

    @classmethod
    def from_dict(
        cls,
        data: Dict[str, Any],
        variant_aliases: Sequence[str] = (),
        variant_sizes: Sequence[float] = (),
    ) -> "CatalogProduct":
        catalog_id = str(
            data.get("product_id")
            or data.get("id")
            or data.get("catalog_id")
            or ""
        ).strip()
        brand = str(
            data.get("brand_name")
            or data.get("brand")
            or ""
        ).strip()
        canonical_name = str(
            data.get("canonical_name")
            or data.get("name")
            or data.get("family_name")
            or ""
        ).strip()
        family_name = str(
            data.get("family_name")
            or canonical_name
            or ""
        ).strip()
        family_id = str(data.get("family_id") or "").strip()

        aliases: List[str] = []
        for value in (
            data.get("aliases") or [],
            variant_aliases,
        ):
            if isinstance(value, str):
                value = [value]
            for alias in value:
                alias = str(alias or "").strip()
                if alias and alias not in aliases:
                    aliases.append(alias)

        # The canonical name is always a valid identity form.
        if canonical_name and canonical_name not in aliases:
            aliases.insert(0, canonical_name)

        formats: List[float] = []
        for value in (
            data.get("formats_ml") or [],
            variant_sizes,
        ):
            if isinstance(value, (str, int, float)):
                value = [value]
            for raw in value:
                try:
                    number = float(raw)
                except (TypeError, ValueError):
                    continue
                if number not in formats:
                    formats.append(number)

        def normalize_ids(values: Any) -> Tuple[str, ...]:
            if isinstance(values, (str, int, float)):
                values = [values]
            return tuple(
                identifier({"v": value}, ("v",))
                for value in (values or [])
                if str(value).strip()
            )

        return cls(
            catalog_id=catalog_id,
            brand=brand,
            name=canonical_name,
            aliases=tuple(aliases),
            formats_ml=tuple(formats),
            gtins=normalize_ids(data.get("gtins") or data.get("ean")),
            mpns=normalize_ids(data.get("mpns") or data.get("mpn")),
            family_id=family_id,
            family_name=family_name,
            catalog_variant=canonical_name,
        )

    @property
    def normalized_brand(self) -> str:
        return normalize(self.brand)

    @property
    def normalized_name(self) -> str:
        return normalize(self.name)

    @property
    def normalized_aliases(self) -> Tuple[str, ...]:
        return tuple(normalize(x) for x in self.aliases if normalize(x))


class ProductMatcher:
    GTIN_KEYS = (
        "gtin", "ean", "ean13", "ean_code", "barcode", "upc",
    )
    MPN_KEYS = (
        "mpn", "manufacturer_part_number", "manufacturerNumber",
    )
    CATALOG_KEYS = (
        "catalog_id", "master_id", "item_group_id", "product_id",
    )
    BRAND_KEYS = ("brand", "manufacturer", "maker")
    NAME_KEYS = ("name", "title", "product_name")

    def __init__(
        self,
        catalog: Iterable[Dict[str, Any] | CatalogProduct] | Dict[str, Any],
        family_registry: Optional[Dict[str, Any] | Iterable[Dict[str, Any]]] = None,
    ) -> None:
        self.family_registry = self._normalize_family_registry(family_registry)

        if isinstance(catalog, dict):
            raw_products = catalog.get("products") or []
            raw_variants = catalog.get("variants") or []
        else:
            raw_products = list(catalog or [])
            raw_variants = []

        variants_by_product: Dict[str, Dict[str, Any]] = {}
        for variant in raw_variants:
            if not isinstance(variant, dict):
                continue
            product_id = str(variant.get("product_id") or "").strip()
            if not product_id:
                continue
            bucket = variants_by_product.setdefault(
                product_id,
                {"aliases": [], "sizes": []},
            )
            aliases = variant.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            for alias in aliases:
                alias = str(alias or "").strip()
                if alias and alias not in bucket["aliases"]:
                    bucket["aliases"].append(alias)
            try:
                size = float(variant.get("size_ml"))
                if size not in bucket["sizes"]:
                    bucket["sizes"].append(size)
            except (TypeError, ValueError):
                pass

        self.catalog: List[CatalogProduct] = []
        for item in raw_products:
            if isinstance(item, CatalogProduct):
                self.catalog.append(item)
                continue
            if not isinstance(item, dict):
                continue
            product_id = str(item.get("product_id") or item.get("id") or item.get("catalog_id") or "").strip()
            bucket = variants_by_product.get(product_id, {"aliases": [], "sizes": []})
            product = CatalogProduct.from_dict(
                item,
                variant_aliases=bucket["aliases"],
                variant_sizes=bucket["sizes"],
            )
            if product.name:
                self.catalog.append(product)

        self._by_gtin: Dict[str, List[CatalogProduct]] = {}
        self._by_mpn: Dict[str, List[CatalogProduct]] = {}
        self._by_catalog_id: Dict[str, CatalogProduct] = {}
        self._by_identity: Dict[Tuple[str, str], CatalogProduct] = {}

        for product in self.catalog:
            if product.catalog_id:
                self._by_catalog_id[normalize(product.catalog_id)] = product
            identity_key = (
                normalize(product.family_id),
                catalog_variant_key(product.name),
            )
            if identity_key[0] and identity_key[1]:
                self._by_identity.setdefault(identity_key, product)
            for value in product.gtins:
                self._by_gtin.setdefault(value, []).append(product)
            for value in product.mpns:
                self._by_mpn.setdefault(value, []).append(product)

    @staticmethod
    def _normalize_family_registry(
        registry: Optional[Dict[str, Any] | Iterable[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        if isinstance(registry, dict):
            families = registry.get("families") or []
        else:
            families = list(registry or [])

        output: List[Dict[str, Any]] = []
        for family in families:
            if not isinstance(family, dict):
                continue

            family_id = str(family.get("family_id") or "").strip()
            brand = str(family.get("brand") or "").strip()
            query_aliases = family.get("query_aliases") or family.get("search_aliases") or []
            if isinstance(query_aliases, str):
                query_aliases = [query_aliases]

            raw_products = family.get("products") or family.get("allowed_variants") or family.get("variants") or []
            variants: List[Dict[str, Any]] = []
            for variant in raw_products:
                if not isinstance(variant, dict):
                    continue
                canonical = str(
                    variant.get("canonical_name") or variant.get("name") or ""
                ).strip()
                if not canonical:
                    continue
                aliases = variant.get("aliases") or []
                if isinstance(aliases, str):
                    aliases = [aliases]
                valid_aliases: List[str] = []
                for value in [canonical, *aliases]:
                    value = str(value or "").strip()
                    if value and value not in valid_aliases:
                        valid_aliases.append(value)
                variants.append(
                    {
                        "canonical_name": canonical,
                        "aliases": valid_aliases,
                        "normalized_aliases": tuple(
                            catalog_variant_key(value) for value in valid_aliases
                            if catalog_variant_key(value)
                        ),
                    }
                )

            output.append(
                {
                    "family_id": family_id,
                    "brand": brand,
                    "query_aliases": [
                        str(value).strip()
                        for value in query_aliases
                        if str(value or "").strip()
                    ],
                    "normalized_query_aliases": tuple(
                        catalog_variant_key(value)
                        for value in query_aliases
                        if catalog_variant_key(value)
                    ),
                    "variants": variants,
                    "excluded_products": tuple(
                        str(value).strip()
                        for value in (family.get("excluded_products") or [])
                        if str(value or "").strip()
                    ),
                    "excluded_aliases": tuple(
                        str(value).strip()
                        for value in (family.get("excluded_aliases") or [])
                        if str(value or "").strip()
                    ),
                }
            )
        return output

    @staticmethod
    def _offer_brand(offer: Dict[str, Any]) -> str:
        value = first_value(offer, ProductMatcher.BRAND_KEYS)
        if value:
            return normalize(value)
        source = _nested_source(offer)
        value = first_value(source, ("source_brand", "brand", "manufacturer"))
        return normalize(value) if value else ""

    @staticmethod
    def _offer_name(offer: Dict[str, Any]) -> str:
        value = first_value(offer, ProductMatcher.NAME_KEYS)
        if value:
            return normalize(value)
        source = _nested_source(offer)
        value = first_value(source, ("source_name", "name", "title"))
        return normalize(value) if value else ""

    NON_FRAGRANCE_MARKERS = (
        "body mist", "body spray", "hair mist", "hair body mist",
        "hair and body mist", "body hair mist", "body lotion",
        "body cream", "body creme", "body shimmer", "body butter",
        "body milk", "body wash", "shower gel", "shower cream",
        "shower foam", "shower oil", "shampoo", "conditioner",
        "deodorant", "antiperspirant", "after shave", "aftershave",
        "hand cream", "hand lotion", "face cream", "face lotion",
        "face mist", "soap", "shower", "bath gel", "bath oil",
        "bagnoschiuma", "gel doccia", "gel douche", "duschgel",
        # Generic non-fragrance packaging/product markers.
        "coffret", "coffrets", "gift set", "giftset", "set regalo",
        "geschenkset", "duftset", "discovery set", "fragrance set",
        "perfume set", "parfum set", "travel set", "bundle",
        "pack", "kit", "duo", "trio", "gift box", "giftbox",
        # Common retailer abbreviations for deodorant / shower products.
        "deo", "deostick", "deo stick", "deodorant stick", "dst", "sg",
        # Generic multilingual after-shave / shaving / cosmetic markers.
        "apres rasage", "apres-rasage", "after shave", "aftershave",
        "rasage", "shaving", "barber", "balsam rasage",
        "duschgel", "dusch gel", "dusche", "body gel",
        "body wash", "body cleanser", "hand wash",
        # Common cosmetic/category labels used by European retailers.
        "lotion", "creme", "cream", "gel douche", "gel doccia",
        "pflege", "kosmetik", "cosmetique", "cosmetica",
    )

    @staticmethod
    def _offer_text(offer: Dict[str, Any]) -> str:
        values = [
            offer.get("name"),
            offer.get("title"),
            offer.get("product_name"),
            offer.get("brand"),
            offer.get("url"),
            offer.get("image"),
            offer.get("image_url"),
            offer.get("image_alt"),
            offer.get("alt"),
        ]
        source = _nested_source(offer)
        values.extend(
            [
                source.get("source_name"),
                source.get("name"),
                source.get("title"),
                source.get("brand"),
                source.get("url"),
                source.get("product_line"),
            ]
        )
        return " ".join(str(value or "") for value in values)

    @classmethod
    def _is_non_fragrance_offer(cls, offer: Dict[str, Any]) -> bool:
        haystack = catalog_norm(cls._offer_text(offer))
        if not haystack:
            return False

        # Generic multi-pack notation (e.g. "2 x", "3x", "x2")
        # is not a single perfume identity.
        if re.search(r"\b\d+\s*x\b|\bx\s*\d+\b", haystack, flags=re.I):
            return True

        if any(
            re.search(rf"\b{re.escape(marker)}\b", haystack, flags=re.I)
            for marker in cls.NON_FRAGRANCE_MARKERS
        ):
            return True

        # Some retailers/CDNs concatenate category words in slugs or image
        # metadata (e.g. "bodylotion", "aftershave", "showergel"). Compare a
        # compact form as a generic fallback; never depend on a perfume name.
        compact_haystack = haystack.replace(" ", "")
        compact_markers = (
            "bodylotion", "bodycream", "bodymist", "bodyspray",
            "deodorant", "aftershave", "showergel", "showercream",
            "handcream", "facelotion", "facecream", "gel douche",
            "gelfdoccia", "duschgel", "giftset", "travelset",
            "geschenkset", "setregalo", "parfumset", "fragranceset",
        )
        return any(marker.replace(" ", "") in compact_haystack for marker in compact_markers)

    @staticmethod
    def _brand_matches(offer_brand: str, family_brand: str) -> bool:
        if not family_brand or not offer_brand:
            return True
        return catalog_norm(offer_brand) == catalog_norm(family_brand)

    @staticmethod
    def _remove_brand(text: str, brand: str) -> str:
        cleaned = catalog_clean_text(text)
        brand_clean = catalog_clean_text(brand)
        if brand_clean:
            cleaned = re.sub(
                rf"\b{re.escape(brand_clean)}\b",
                " ",
                cleaned,
                flags=re.I,
            )
        return re.sub(r"\s+", " ", cleaned).strip()

    def _family_for_query(self, query: str) -> Optional[Dict[str, Any]]:
        query_key = catalog_variant_key(query)
        if not query_key:
            return None

        for family in self.family_registry:
            if query_key in family["normalized_query_aliases"]:
                return family

        padded = f" {query_key} "
        for family in self.family_registry:
            for alias in family["normalized_query_aliases"]:
                if alias and f" {alias} " in padded:
                    return family
        return None

    def _requested_variant(
        self,
        query: str,
        family: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        query_key = self._remove_brand(query, family.get("brand", ""))
        query_key = catalog_variant_key(query_key)
        for variant in family["variants"]:
            if query_key in variant["normalized_aliases"]:
                return variant
        return None

    def _family_variant_for_offer(
        self,
        offer: Dict[str, Any],
        family: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        # Family searches are fragrance searches. Reject explicit non-fragrance
        # categories centrally, before variant resolution, so no retailer
        # scraper needs store-specific product filters.
        if self._is_non_fragrance_offer(offer):
            return None

        offer_brand = self._offer_brand(offer)
        if not self._brand_matches(offer_brand, family.get("brand", "")):
            return None

        raw_name = first_value(offer, self.NAME_KEYS)
        if not raw_name:
            source = _nested_source(offer)
            raw_name = first_value(source, ("source_name", "name", "title"))

        candidate = self._remove_brand(raw_name, family.get("brand", ""))
        candidate_key = catalog_variant_key(candidate)
        if not candidate_key:
            return None

        excluded = tuple(
            catalog_variant_key(value)
            for value in (*family.get("excluded_products", ()), *family.get("excluded_aliases", ()))
        )
        if candidate_key in excluded:
            return None

        for variant in family["variants"]:
            if candidate_key in variant["normalized_aliases"]:
                return variant

        # Retailers may append or insert audience/editorial labels around the
        # actual variant name (for example "Hawas Kobra for Men - Heren",
        # "Hawas Men Black - Heren", or "Hawas Women Eclat - Dames").
        # These labels are not part of the Hawas variant identity. Preserve
        # exact alias matching above first, then try a generic normalization
        # that removes only explicit audience labels and Dutch storefront
        # gender labels. This keeps "Hawas for Her" and "Hawas for Him"
        # distinct because their exact aliases win before this fallback.
        editorial_tokens = {
            "men", "women", "man", "woman", "heren", "dames",
        }
        stripped_tokens = [
            token for token in candidate_key.split()
            if token not in editorial_tokens
        ]
        stripped_key = " ".join(stripped_tokens).strip()
        if stripped_key != candidate_key:
            for variant in family["variants"]:
                if stripped_key in variant["normalized_aliases"]:
                    return variant

        # "for men" / "for women" can survive as two tokens after the first
        # pass; remove the complete phrase only when it produces an exact
        # known alias.
        stripped_for_tokens = re.sub(
            r"\bfor\s+(?:men|women|him|her)\b",
            " ",
            candidate_key,
            flags=re.I,
        )
        stripped_for_tokens = re.sub(r"\s+", " ", stripped_for_tokens).strip()
        if stripped_for_tokens != candidate_key:
            for variant in family["variants"]:
                if stripped_for_tokens in variant["normalized_aliases"]:
                    return variant
        return None

    def _catalog_product_for_family_variant(
        self,
        family: Dict[str, Any],
        variant: Dict[str, Any],
    ) -> Optional[CatalogProduct]:
        family_id = normalize(family.get("family_id", ""))
        canonical_key = catalog_variant_key(variant.get("canonical_name", ""))

        product = self._by_identity.get((family_id, canonical_key))
        if product is not None:
            return product

        for candidate in self.catalog:
            if family_id and normalize(candidate.family_id) != family_id:
                continue
            if catalog_variant_key(candidate.name) == canonical_key:
                return candidate
        return None

    def _build_family_result(
        self,
        offer: Dict[str, Any],
        family: Dict[str, Any],
        variant: Dict[str, Any],
    ) -> Dict[str, Any]:
        catalog_product = self._catalog_product_for_family_variant(family, variant)
        canonical_name = variant["canonical_name"]
        family_id = str(family.get("family_id") or "").strip()

        if catalog_product is not None:
            catalog_id = catalog_product.catalog_id
            canonical_brand = catalog_product.brand or str(family.get("brand") or "").strip()
            family_name = catalog_product.family_name or family.get("query_aliases", [canonical_name])[0]
        else:
            catalog_id = stable_family_id(family_id, canonical_name)
            canonical_brand = str(family.get("brand") or "").strip()
            family_name = str((family.get("query_aliases") or [canonical_name])[0]).strip()

        result = dict(offer)
        result.update(
            {
                "catalog_id": catalog_id,
                "family_id": family_id,
                "family_name": family_name,
                "canonical_name": canonical_name,
                "canonical_brand": canonical_brand,
                "catalog_variant": canonical_name,
                "match_method": "family_registry_alias",
                "match_score": 1.0,
                "product_identity": catalog_id,
            }
        )

        resolved_size = size_ml(offer)
        if resolved_size is not None:
            result["size_ml"] = resolved_size
            result["variant_id"] = f"{catalog_id}:{resolved_size:g}"
        else:
            result["variant_id"] = catalog_id

        return result

    def _match_family(
        self,
        offer: Dict[str, Any],
        query: str,
        family: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        variant = self._family_variant_for_offer(offer, family)
        if variant is None:
            return None

        query_is_family = catalog_variant_key(query) in family["normalized_query_aliases"]
        requested = self._requested_variant(query, family)

        if not query_is_family and requested is None:
            return None

        if not query_is_family and requested["canonical_name"] != variant["canonical_name"]:
            return None

        return self._build_family_result(offer, family, variant)

    def match(
        self,
        offer: Dict[str, Any],
        query: str,
    ) -> Optional[Dict[str, Any]]:
        started = time.perf_counter()

        store = str(offer.get("store") or "")
        raw_name = str(
            offer.get("name") or offer.get("title") or offer.get("product_name") or ""
        )

        # Never treat samples/decants/testers as full-size fragrance offers.
        # This guard runs before family and generic matching, so removing bottle
        # size from identity normalization can never turn a sample into a product.
        identity_text = " ".join(
            str(offer.get(key) or "")
            for key in ("name", "title", "product_name")
        )
        if re.search(
            r"\b(?:sample|samples|decant|decants|tester|testeur|testers)\b",
            identity_text,
            flags=re.I,
        ):
            print(
                "SCENTHUNTER: MATCHER_REJECTED "
                f"store={store!r} name={raw_name!r} "
                "method=sample_or_tester",
                flush=True,
            )
            return None

        family = self._family_for_query(query)
        if family is not None:
            result = self._match_family(offer, query, family)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            if result is None:
                print(
                    "SCENTHUNTER: MATCHER_REJECTED "
                    f"store={store!r} name={raw_name!r} "
                    f"method=rejected elapsed_ms={elapsed_ms:.1f}",
                    flush=True,
                )
                return None

            print(
                "SCENTHUNTER: MATCHER_RESULT "
                f"store={store!r} raw_name={raw_name!r} "
                f"family_id={result.get('family_id')!r} "
                f"canonical_name={result.get('canonical_name')!r} "
                f"method={result.get('match_method')} elapsed_ms={elapsed_ms:.1f}",
                flush=True,
            )
            return result

        return self._match_generic(offer, query, started)

    def build_query_scope(self, query: str) -> Dict[str, Any]:
        """Build a catalog-derived scope for the current retailer query.

        The scope is deliberately based only on catalog identity text.  It does
        not use images, prices, URLs or retailer-specific rules.
        """
        q = catalog_variant_key(query)
        q_tokens = set(q.split())
        candidates: List[CatalogProduct] = []

        for product in self.catalog:
            texts = [product.name, *product.aliases]
            normalized = [catalog_variant_key(value) for value in texts if value]
            best = 0.0
            for candidate in normalized:
                if not candidate:
                    continue
                c_tokens = set(candidate.split())
                if not q_tokens or not c_tokens:
                    continue
                inter = len(q_tokens & c_tokens)
                recall = inter / len(q_tokens)
                precision = inter / len(c_tokens)
                score = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
                if q == candidate:
                    score = 1.0
                elif q and (
                    candidate.startswith(q + " ")
                    or candidate.endswith(" " + q)
                    or (" " + q + " ") in (" " + candidate + " ")
                ):
                    # Phrase containment is useful for family/variant queries
                    # (e.g. "Boss Bottled" -> "Boss Bottled Elixir"), but
                    # never use arbitrary substring containment.  Otherwise a
                    # short catalog name such as "Le" can become a candidate
                    # for an unrelated query simply because "le" occurs inside
                    # another word.
                    score = max(score, 0.90)
                elif len(q.split()) == 1 and q in c_tokens:
                    # Single-token family queries such as "Hawas" should keep
                    # the variants "Hawas Ice", "Hawas Kobra", etc.
                    score = max(score, 0.75)
                best = max(best, score)
            if best >= 0.55:
                candidates.append(product)

        return {
            "query": query,
            "normalized_query": q,
            "candidates": candidates,
        }

    @staticmethod
    def _offer_url_identity_texts(offer: Dict[str, Any]) -> Tuple[str, ...]:
        """Return generic identity text derived from offer URLs.

        URLs are used only as a secondary identity signal when the retailer
        name is too generic.  The matcher never requires a particular retailer
        or a product-specific URL rule.
        """
        values: List[str] = []
        source = _nested_source(offer)
        for value in (
            offer.get("url"),
            offer.get("product_url"),
            source.get("url"),
            source.get("product_url"),
        ):
            text = str(value or "").strip()
            if not text:
                continue
            path = re.sub(r"[?#].*$", "", text)
            path = re.sub(r"^https?://", "", path, flags=re.I)
            path = re.sub(r"[^a-z0-9/]+", " ", path.lower())
            path = re.sub(r"\s*/\s*", "/", path)
            path = re.sub(r"\s+", " ", path).strip(" /")
            if path and path not in values:
                values.append(path)
        return tuple(values)

    @staticmethod
    def _url_identity_text(value: str) -> str:
        """Normalize a URL path while retaining variant-bearing words."""
        text = normalize(value)
        text = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|oz|fl oz)\b", " ", text)
        text = re.sub(
            r"\beau\s+de\s+parfum\b",
            " parfum ",
            text,
            flags=re.I,
        )
        text = re.sub(
            r"\b(?:eau\s+de\s+toilette|eau\s+de\s+cologne|eau\s+fraiche|"
            r"extrait\s+de\s+parfum|edp|edt|edc|spray|vapo|vaporisateur|refillable|refill)\b",
            " ",
            text,
            flags=re.I,
        )
        text = re.sub(r"\b(?:man|men|woman|women|unisex)\b.*$", " ", text)
        text = re.sub(r"\bz\d+\b.*$", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    @staticmethod
    def _url_catalog_identity_text(value: Any) -> str:
        """Normalize a catalog identity for URL comparison without erasing variant words."""
        text = normalize(value)
        text = re.sub(r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|oz|fl oz)\b", " ", text)
        text = re.sub(
            r"\b(?:eau\s+de\s+toilette|eau\s+de\s+cologne|eau\s+fraiche|"
            r"eau\s+de\s+parfum|extrait\s+de\s+parfum|edp|edt|edc|spray)\b",
            " ",
            text,
            flags=re.I,
        )
        return re.sub(r"\s+", " ", text).strip()

    @classmethod
    def _url_candidate_score(
        cls,
        offer: Dict[str, Any],
        product: CatalogProduct,
    ) -> Tuple[float, str]:
        best = 0.0
        matched_alias = ""

        for raw_url in cls._offer_url_identity_texts(offer):
            # Ignore the host.  The path/slug is the identity-bearing part.
            path = raw_url.split("/", 1)[1] if "/" in raw_url else raw_url
            segments = [segment for segment in path.split("/") if segment]
            if not segments:
                segments = [path]

            # Compare the complete product slug first.
            for raw_variant in segments[-1:] + [path]:
                url_name = cls._url_identity_text(raw_variant)
                if not url_name:
                    continue
                url_tokens_list = url_name.split()
                if not url_tokens_list:
                    continue

                brand_tokens = ProductMatcher._offer_brand(offer).split()

                for alias in (product.name, *product.aliases):
                    candidate = cls._url_catalog_identity_text(alias)
                    if not candidate:
                        continue
                    c_tokens = set(candidate.split())

                    # Remove URL/domain boilerplate and brand tokens that are
                    # not part of this catalog identity.  This keeps the
                    # comparison generic while preserving overlapping words
                    # such as "Boss" when they are actually part of the name.
                    candidate_url_tokens = list(url_tokens_list)
                    generic_url_tokens = {
                        "www", "http", "https", "produit", "product",
                        "products", "prodotto", "producto", "html", "aspx",
                    }
                    candidate_url_tokens = [
                        token for token in candidate_url_tokens
                        if token not in generic_url_tokens and not token.isdigit()
                    ]
                    counts = Counter(candidate_url_tokens)
                    for token in brand_tokens:
                        if token not in c_tokens:
                            counts.pop(token, None)
                        elif counts[token] > 1:
                            counts[token] -= 1
                    candidate_url_tokens = [
                        token for token in candidate_url_tokens
                        if counts[token] > 0
                    ]
                    n_tokens = set(candidate_url_tokens)
                    if not n_tokens:
                        continue

                    inter = len(n_tokens & c_tokens)
                    if not inter:
                        continue
                    recall = inter / len(c_tokens)
                    precision = inter / len(n_tokens)
                    score = (
                        2 * recall * precision / (recall + precision)
                        if recall + precision
                        else 0.0
                    )
                    if n_tokens == c_tokens:
                        score = 1.0
                    if score > best:
                        best = score
                        matched_alias = alias

        return best, matched_alias

    @staticmethod
    def _query_candidate_score(offer_name: str, product: CatalogProduct) -> Tuple[float, str]:
        name = catalog_variant_key(offer_name)
        best = 0.0
        matched_alias = ""
        for alias in (product.name, *product.aliases):
            candidate = catalog_variant_key(alias)
            if not candidate:
                continue
            if name == candidate:
                return 1.0, alias
            n_tokens = set(name.split())
            c_tokens = set(candidate.split())
            inter = len(n_tokens & c_tokens)
            recall = inter / len(c_tokens) if c_tokens else 0.0
            precision = inter / len(n_tokens) if n_tokens else 0.0
            f = 2 * recall * precision / (recall + precision) if recall + precision else 0.0
            if candidate in name:
                f = max(f, 0.92)
            if f > best:
                best = f
                matched_alias = alias
        return best, matched_alias

    def match_offer(
        self,
        offer: Dict[str, Any],
        query_scope: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Resolve a raw offer against the catalog-derived query scope.

        Unresolved offers are returned as ``status=unresolved`` rather than
        discarded.  Only an explicit non-fragrance/sample rejection is a hard
        rejection here.
        """
        if self._is_non_fragrance_offer(offer):
            return {"status": "rejected", "reject_reason": "non_fragrance"}

        candidates = list(query_scope.get("candidates") or [])
        offer_name = self._offer_name(offer)
        offer_brand = self._offer_brand(offer)
        if not offer_name or not candidates:
            return {"status": "unresolved", "confidence": 0.0}

        best_product = None
        best_score = 0.0
        best_alias = ""

        eligible: List[CatalogProduct] = []
        for product in candidates:
            if offer_brand and product.normalized_brand:
                brand = normalize(product.brand)
                if offer_brand != brand and offer_brand not in brand and brand not in offer_brand:
                    continue
            eligible.append(product)

        # First establish whether the URL contains a sufficiently specific
        # catalog identity.  If it does, use URL scores consistently across
        # all candidates so an exact generic name (e.g. "Boss Bottled") cannot
        # defeat a more specific variant found in the URL.
        url_matches = [
            (product, *self._url_candidate_score(offer, product))
            for product in eligible
        ]
        best_url_product = None
        best_url_score = 0.0
        best_url_alias = ""
        for product, url_score, url_alias in url_matches:
            if url_score > best_url_score:
                best_url_product = product
                best_url_score = url_score
                best_url_alias = url_alias

        use_url_identity = best_url_product is not None and best_url_score >= 0.70

        for product, url_score, url_alias in url_matches:
            if use_url_identity:
                score, alias = url_score, url_alias
            else:
                score, alias = self._query_candidate_score(offer_name, product)

            if score > best_score:
                best_product = product
                best_score = score
                best_alias = alias

        if best_product is None or best_score < 0.72:
            return {"status": "unresolved", "confidence": round(best_score, 4)}

        return {
            "status": "matched",
            "catalog_id": best_product.catalog_id,
            "brand": best_product.brand,
            "family": best_product.family_name or best_product.name,
            "variant": best_product.catalog_variant or best_product.name,
            "canonical_name": best_product.name,
            "confidence": round(best_score, 4),
            "matched_alias": best_alias,
        }

    def _best_match(self, offer: Dict[str, Any]) -> Tuple[Optional[CatalogProduct], str, float]:
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

        best_product: Optional[CatalogProduct] = None
        best_score = 0.0
        best_method = "none"

        for product in self.catalog:
            score = self._text_score(brand, name, product)
            if score > best_score:
                best_product = product
                best_score = score
                best_method = "exact_name" if score >= 0.94 else "token_score"

        if best_product is None or best_score < 0.86:
            return None, "none", best_score
        return best_product, best_method, best_score

    @staticmethod
    def _text_score(
        brand: str,
        name: str,
        product: CatalogProduct,
    ) -> float:
        brand_score = 1.0 if brand and brand == product.normalized_brand else 0.0
        best = 0.0

        for candidate in (product.normalized_name, *product.normalized_aliases):
            if not candidate:
                continue
            if name == candidate:
                best = max(best, 1.0)
                continue

            query_tokens = set(name.split())
            candidate_tokens = set(candidate.split())
            intersection = len(query_tokens & candidate_tokens)
            recall = intersection / len(candidate_tokens) if candidate_tokens else 0.0
            precision = intersection / max(1, len(query_tokens))
            f_score = (
                2 * recall * precision / (recall + precision)
                if recall + precision
                else 0.0
            )

            # Preserve the original matcher rule: generic matching must not
            # promote a shorter query merely because it is a substring of a
            # longer canonical name.
            if candidate in name:
                f_score = max(f_score, 0.92)

            best = max(best, f_score)

        return 0.45 + 0.55 * best if brand_score else 0.95 * best

    def _match_generic(
        self,
        offer: Dict[str, Any],
        query: str,
        started: float,
    ) -> Optional[Dict[str, Any]]:
        product, method, score = self._best_match(offer)
        elapsed_ms = (time.perf_counter() - started) * 1000.0

        if product is None:
            print(
                "SCENTHUNTER: MATCHER_UNRESOLVED "
                f"store={offer.get('store', '')!r} "
                f"name={offer.get('name', '')!r} "
                f"score={score:.4f} elapsed_ms={elapsed_ms:.1f}",
                flush=True,
            )
            return None

        result = dict(offer)
        result.update(
            {
                "catalog_id": product.catalog_id,
                "family_id": product.family_id,
                "family_name": product.family_name,
                "canonical_name": product.name,
                "canonical_brand": product.brand,
                "catalog_variant": product.catalog_variant or product.name,
                "match_method": method if method != "none" else "generic",
                "match_score": round(score, 4),
                "product_identity": product.catalog_id,
            }
        )

        resolved_size = size_ml(offer)
        if resolved_size is not None:
            result["size_ml"] = resolved_size
            result["variant_id"] = f"{product.catalog_id}:{resolved_size:g}"
        else:
            result["variant_id"] = product.catalog_id

        print(
            "SCENTHUNTER: MATCHER_RESULT "
            f"store={offer.get('store', '')!r} "
            f"raw_name={offer.get('name', '')!r} "
            f"catalog_id={product.catalog_id!r} "
            f"canonical_name={product.name!r} "
            f"method={result['match_method']} score={score:.4f} "
            f"elapsed_ms={elapsed_ms:.1f}",
            flush=True,
        )
        return result


_MATCHER_CACHE: Dict[Tuple[int, int], ProductMatcher] = {}


def match_product(
    product: Dict[str, Any],
    query: str,
    catalog: Iterable[Dict[str, Any] | CatalogProduct] | Dict[str, Any],
    family_registry: Optional[Dict[str, Any] | Iterable[Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    """Resolve one scraper candidate through the single central matcher."""
    key = (id(catalog), id(family_registry))
    matcher = _MATCHER_CACHE.get(key)
    if matcher is None:
        matcher = ProductMatcher(
            catalog=catalog,
            family_registry=family_registry,
        )
        _MATCHER_CACHE[key] = matcher
    return matcher.match(product, query)


def offer_key(offer: Dict[str, Any]) -> Tuple[str, str, str, str]:
    store = normalize(
        offer.get("store") or _nested_source(offer).get("store") or ""
    )
    identity = normalize(
        offer.get("product_identity") or offer.get("catalog_id") or ""
    )
    resolved_size = size_ml(offer)
    size = "" if resolved_size is None else f"{resolved_size:g}"
    url = (
        str(offer.get("url") or _nested_source(offer).get("url") or "")
        .split("#", 1)[0]
        .split("?", 1)[0]
        .strip()
        .lower()
    )
    return store, identity, size, url


def attach_matches(
    offers: Iterable[Dict[str, Any]],
    catalog: Iterable[Dict[str, Any] | CatalogProduct] | Dict[str, Any],
    family_registry: Optional[Dict[str, Any] | Iterable[Dict[str, Any]]] = None,
    query: str = "",
) -> List[Dict[str, Any]]:
    matcher = ProductMatcher(catalog, family_registry=family_registry)
    output: List[Dict[str, Any]] = []
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        matched = matcher.match(offer, query)
        if matched is not None:
            output.append(matched)
    return output
