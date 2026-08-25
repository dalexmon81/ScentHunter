"""ScentHunter central product identity matcher.

The matcher is the single identity layer between RAW scraper output and the
frontend. Scrapers may expose their source data both at top level and inside
the RAW ``source`` / ``identity`` / ``attributes`` blocks; this module accepts
both forms without adding store- or-product-specific exceptions.
"""
from __future__ import annotations

import hashlib
import re
import time
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


def first_value(
    item: Dict[str, Any],
    keys: Sequence[str],
) -> str:
    for key in keys:
        value = item.get(key)

        if value is not None and str(value).strip():
            return str(value).strip()

    return ""


def _nested_source(
    item: Dict[str, Any],
) -> Dict[str, Any]:
    value = item.get("source")

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _nested_identity(
    item: Dict[str, Any],
) -> Dict[str, Any]:
    value = item.get("identity")

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _nested_attributes(
    item: Dict[str, Any],
) -> Dict[str, Any]:
    value = item.get("attributes")

    return (
        value
        if isinstance(value, dict)
        else {}
    )


def _nested_attribute_value(
    item: Dict[str, Any],
    key: str,
) -> Any:
    value = _nested_attributes(item).get(key)

    if isinstance(value, dict):
        return value.get("value")

    return value


def identifier(
    item: Dict[str, Any],
    keys: Sequence[str],
) -> str:
    value = first_value(item, keys)

    if not value:
        identity = _nested_identity(item)
        value = first_value(identity, keys)

    return (
        normalize(value).replace(" ", "")
        if value
        else ""
    )


def size_ml(
    item: Dict[str, Any],
) -> Optional[float]:

    explicit = item.get("size_ml")

    if explicit in (None, ""):
        explicit = _nested_attribute_value(
            item,
            "size_ml",
        )

    if explicit not in (None, ""):
        try:
            return float(
                str(explicit).replace(",", ".")
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

    text = " ".join(
        str(item.get(k) or "")
        for k in (
            "name",
            "title",
            "product_name",
            "size",
            "format",
        )
    )

    source = _nested_source(item)

    text += " " + " ".join(
        str(source.get(k) or "")
        for k in (
            "source_name",
            "name",
        )
    )

    match = re.search(
        r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
        re.I,
    )

    if not match:
        return None

    value = float(
        match.group(1).replace(",", ".")
    )

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
    def from_dict(
        cls,
        data: Dict[str, Any],
    ):
        return cls(
            str(
                data.get("id")
                or data.get("catalog_id")
                or ""
            ).strip(),

            str(
                data.get("brand")
                or ""
            ).strip(),

            str(
                data.get("name")
                or ""
            ).strip(),

            tuple(
                str(x).strip()
                for x in (
                    data.get("aliases")
                    or []
                )
                if str(x).strip()
            ),

            tuple(
                float(x)
                for x in (
                    data.get("formats_ml")
                    or []
                )
                if str(x).strip()
            ),

            tuple(
                identifier(
                    {"v": x},
                    ("v",),
                )
                for x in (
                    data.get("gtins")
                    or data.get("ean")
                    or []
                )
                if str(x).strip()
            ),

            tuple(
                identifier(
                    {"v": x},
                    ("v",),
                )
                for x in (
                    data.get("mpns")
                    or data.get("mpn")
                    or []
                )
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
        return tuple(
            normalize(x)
            for x in self.aliases
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

    def __init__(
        self,
        catalog: Iterable[
            Dict[str, Any] | CatalogProduct
        ],
    ):

        self.catalog = [
            x
            if isinstance(
                x,
                CatalogProduct,
            )
            else CatalogProduct.from_dict(x)
            for x in catalog
        ]

        self._by_gtin = {}
        self._by_mpn = {}
        self._by_catalog_id = {}

        for product in self.catalog:

            if product.catalog_id:
                self._by_catalog_id[
                    normalize(
                        product.catalog_id
                    )
                ] = product

            for value in product.gtins:
                self._by_gtin.setdefault(
                    value,
                    [],
                ).append(product)

            for value in product.mpns:
                self._by_mpn.setdefault(
                    value,
                    [],
                ).append(product)

    def _offer_brand(
        self,
        offer: Dict[str, Any],
    ) -> str:

        value = first_value(
            offer,
            self.BRAND_KEYS,
        )

        if value:
            return normalize(value)

        source = _nested_source(offer)

        value = first_value(
            source,
            (
                "source_brand",
                "brand",
                "manufacturer",
            ),
        )

        return (
            normalize(value)
            if value
            else ""
        )

    def _offer_name(
        self,
        offer: Dict[str, Any],
    ) -> str:

        value = first_value(
            offer,
            self.NAME_KEYS,
        )

        if value:
            return normalize(value)

        source = _nested_source(offer)

        value = first_value(
            source,
            (
                "source_name",
                "name",
                "title",
            ),
        )

        return (
            normalize(value)
            if value
            else ""
        )

    def match(
        self,
        offer: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:

        # ========================================================
        # DIAGNOSTICA TEMPORANEA
        # ========================================================

        started = time.perf_counter()

        store = str(
            offer.get("store")
            or ""
        )

        name = str(
            offer.get("name")
            or offer.get("title")
            or offer.get("product_name")
            or ""
        )

        brand = str(
            offer.get("brand")
            or ""
        )

        price = str(
            offer.get("price")
            or ""
        )

        url = str(
            offer.get("url")
            or ""
        )

        raw_size = (
            offer.get("size_ml")
            or offer.get("size")
            or offer.get("format")
            or ""
        )

        print(
            "SCENTHUNTER: MATCHER_RAW "
            f"store={store!r} "
            f"brand={brand!r} "
            f"name={name!r} "
            f"size={raw_size!r} "
            f"price={price!r} "
            f"url={url!r}",
            flush=True,
        )

        # ========================================================
        # MATCHING ORIGINALE
        # ========================================================

        product, method, score = (
            self._best_match(offer)
        )

        if product is None:
            return None

        elapsed_ms = (
            time.perf_counter()
            - started
        ) * 1000.0

        # ========================================================
        # DIAGNOSTICA RISULTATO
        # ========================================================

        if product is None:

            print(
                "SCENTHUNTER: "
                "MATCHER_UNRESOLVED "
                f"store={store!r} "
                f"name={name!r} "
                f"score={score:.4f} "
                f"elapsed_ms={elapsed_ms:.1f}",
                flush=True,
            )

            return None

        print(
            "SCENTHUNTER: "
            "MATCHER_RESULT "
            f"store={store!r} "
            f"raw_name={name!r} "
            f"catalog_id={product.catalog_id!r} "
            f"canonical_name={product.name!r} "
            f"method={method} "
            f"score={score:.4f} "
            f"elapsed_ms={elapsed_ms:.1f}",
            flush=True,
        )

        result = dict(offer)

        # Preserve the RAW blocks exactly as supplied by
        # the scraper while exposing the canonical identity
        # as flat fields for the API/frontend.

        result.update(
            catalog_id=product.catalog_id,
            canonical_brand=product.brand,
            canonical_name=product.name,
            match_method=method,
            match_score=round(
                score,
                4,
            ),
            product_identity=self._identity_for_product(product),
        )

        resolved_size = size_ml(offer)

        if resolved_size is not None:
            result["size_ml"] = (
                resolved_size
            )

        result["variant_id"] = result["product_identity"]

        if resolved_size is not None:
            result["offer_variant_id"] = (
                f"{result['product_identity']}:{resolved_size:g}"
            )
        else:
            result["offer_variant_id"] = (
                result["product_identity"]
            )

        return result

    def _best_match(
        self,
        offer: Dict[str, Any],
    ) -> Tuple[Optional[CatalogProduct], str, float]:
        if self._is_non_fragrance_offer(offer):
            return None, "non_fragrance", 0.0

        gtin = identifier(offer, self.GTIN_KEYS)
        if gtin and len(self._by_gtin.get(gtin, [])) == 1:
            return self._by_gtin[gtin][0], "gtin", 1.0

        mpn = identifier(offer, self.MPN_KEYS)
        if mpn and len(self._by_mpn.get(mpn, [])) == 1:
            return self._by_mpn[mpn][0], "mpn", 0.99

        catalog_id = identifier(offer, self.CATALOG_KEYS)
        if catalog_id and catalog_id in self._by_catalog_id:
            product = self._by_catalog_id[catalog_id]

            if self._product_is_fragrance(product):
                return product, "catalog_id", 0.98

            return None, "non_fragrance", 0.0

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
            if not self._product_is_fragrance(product):
                continue

            if not self._brand_matches(brand, product):
                continue

            score = self._name_score(name, product)

            if score > 0:
                ranked.append((score, product))

        ranked.sort(
            key=lambda item: (
                item[0],
                len(
                    normalize(
                        getattr(item[1], "name", "")
                    ).split()
                ),
            ),
            reverse=True,
        )

        if not ranked:
            return None, "none", 0.0

        best_score = ranked[0][0]

        tied = [
            item
            for item in ranked
            if abs(item[0] - best_score) < 0.0001
        ]

        if len(tied) > 1:
            exact = [
                item
                for item in tied
                if normalize(item[1].name) == name
            ]

            if len(exact) == 1:
                score, product = exact[0]
                return product, "exact_name", score

            return None, "ambiguous", best_score

        score, product = ranked[0]

        if score >= 0.96:
            return product, "exact_name", score

        if score >= 0.88:
            return product, "token_score", score

        return None, "none", score
    def _is_non_fragrance_offer(
        self,
        offer: Dict[str, Any],
    ) -> bool:
        values = [
            offer.get("title"),
            offer.get("name"),
            offer.get("product_name"),
            offer.get("category"),
            offer.get("product_type"),
            offer.get("packaging_type"),
            offer.get("description"),
        ]

        text = normalize(
            " ".join(
                str(value or "")
                for value in values
            )
        )

        excluded_terms = (
            "air freshener",
            "air freshner",
            "ambientador",
            "desodorisant",
            "desodoriser",
            "room spray",
            "car fragrance",
            "home fragrance",
            "candle",
            "diffuser",
            "diffusor",
            "miniature",
            "miniatur",
            "etui",
            "case",
            "pouch",
        )

        return any(
            re.search(
                rf"(?<!\w){re.escape(term)}(?!\w)",
                text,
            )
            for term in excluded_terms
        )

    def _product_is_fragrance(
        self,
        product: CatalogProduct,
    ) -> bool:
        values = [
            getattr(product, "name", ""),
            getattr(product, "brand", ""),
            getattr(product, "category", ""),
            getattr(product, "product_type", ""),
            getattr(product, "packaging_type", ""),
        ]

        text = normalize(
            " ".join(
                str(value or "")
                for value in values
            )
        )

        excluded_terms = (
            "air freshener",
            "air freshner",
            "ambientador",
            "desodorisant",
            "room spray",
            "candle",
            "diffuser",
            "miniature",
            "miniatur",
            "etui",
            "case",
            "pouch",
        )

        return not any(
            re.search(
                rf"(?<!\w){re.escape(term)}(?!\w)",
                text,
            )
            for term in excluded_terms
        )

    def _identity_for_product(
        self,
        product: CatalogProduct,
    ) -> str:
        family_id = str(
            getattr(product, "family_id", "")
            or getattr(product, "catalog_id", "")
            or ""
        ).strip()

        variant = str(
            getattr(product, "catalog_variant", "")
            or getattr(product, "canonical_name", "")
            or getattr(product, "name", "")
            or ""
        ).strip()

        concentration = str(
            getattr(product, "concentration", "")
            or ""
        ).strip()

        parts = [
            normalize(family_id),
            normalize(variant),
            normalize(concentration),
        ]

        return "::".join(
            part
            for part in parts
            if part
        )


    @staticmethod
    def _text_score(
        brand: str,
        name: str,
        product: CatalogProduct,
    ):

        brand_score = (
            1.0
            if (
                brand
                and brand
                == product.normalized_brand
            )
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
                best = max(
                    best,
                    1.0,
                )
                continue

            query_tokens = set(
                name.split()
            )

            candidate_tokens = set(
                candidate.split()
            )

            intersection = len(
                query_tokens
                & candidate_tokens
            )

            recall = (
                intersection
                / len(candidate_tokens)
                if candidate_tokens
                else 0.0
            )

            precision = (
                intersection
                / max(
                    1,
                    len(query_tokens),
                )
            )

            f_score = (
                2
                * recall
                * precision
                / (
                    recall
                    + precision
                )
                if recall + precision
                else 0.0
            )

            # A shorter name must NOT match a longer
            # canonical product name merely because it
            # is a substring.
            #
            # Example:
            # Hawas must not become Hawas Ice.

            if candidate in name:
                f_score = max(
                    f_score,
                    0.92,
                )

            best = max(
                best,
                f_score,
            )

        return (
            0.45 + 0.55 * best
            if brand_score
            else 0.95 * best
        )


def offer_key(
    offer: Dict[str, Any],
) -> Tuple[
    str,
    str,
    str,
    str,
]:

    store = normalize(
        offer.get("store")
        or _nested_source(
            offer
        ).get("store")
        or ""
    )

    identity = normalize(
        offer.get(
            "product_identity"
        )
        or offer.get(
            "catalog_id"
        )
        or ""
    )

    resolved_size = size_ml(
        offer
    )

    size = (
        ""
        if resolved_size is None
        else f"{resolved_size:g}"
    )

    url = (
        str(
            offer.get("url")
            or _nested_source(
                offer
            ).get("url")
            or ""
        )
        .split("#", 1)[0]
        .split("?", 1)[0]
        .strip()
        .lower()
    )

    return (
        store,
        identity,
        size,
        url,
    )


def attach_matches(
    offers: Iterable[
        Dict[str, Any]
    ],
    catalog: Iterable[
        Dict[str, Any]
        | CatalogProduct
    ],
) -> List[
    Dict[str, Any]
]:

    matcher = ProductMatcher(
        catalog
    )

    output = []

    for offer in offers:

        if isinstance(
            offer,
            dict,
        ):

            matched = matcher.match(
                offer
            )

            if matched is not None:
                output.append(
                    matched
                )

    return output
