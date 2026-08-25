from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import threading
import traceback
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


# ============================================================
# ScentHunter API
# ============================================================

app = FastAPI(
    title="ScentHunter API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CONFIGURAZIONE
# ============================================================

STORES = [
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "notino",
]

BASE_DIR = os.path.dirname(__file__)
HISTORY_PATH = os.path.join(BASE_DIR, "price_history.json")

FRONTEND_INDEX = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "index.html"
)

FAMILY_REGISTRY_PATH = os.path.join(
    BASE_DIR,
    "family_registry.json",
)

# The registry is project knowledge, not store-specific logic.
# Accept the normal backend location and the project-root location so a
# deployment cannot silently disable family validation because the JSON was
# placed one directory above main.py.
FAMILY_REGISTRY_CANDIDATE_PATHS = (
    FAMILY_REGISTRY_PATH,
    os.path.join(os.path.dirname(BASE_DIR), "family_registry.json"),
)

NON_PERFUME = {
    # Confezioni / prodotti multipli: non sono una singola referenza profumo.
    "gift set",
    "set regalo",
    "set",
    "discovery set",
    "fragrance set",
    "perfume set",
    "parfum set",
    "coffret",
    "coffret cadeau",
    "cofanetto",
    "bundle",
    "pack",
    "travel set",
    "kit",
    "duo",
    "trio",
    "mystery box",
    "gift box",
    # Prodotti non costituiti dalla singola referenza profumo.
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
}

IGNORED_WORDS = {
    "eau",
    "de",
    "parfum",
    "perfume",
    "edp",
    "edt",
    "extrait",
    "spray",
    "ml",
    "for",
    "by",
}

GLOBAL_SEARCH_TIMEOUT = 120


# ============================================================
# NORMALIZZAZIONE
# ============================================================

def norm(value: Any) -> str:
    value = str(value or "").strip().lower()

    # Unicode normalization: e, è, é, ê, ë, etc. are matched
    # as the same base letter. This is global and query-independent.
    value = unicodedata.normalize("NFKD", value)
    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    value = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        value,
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


# ============================================================
# CONOSCENZA DELLE FAMIGLIE
# ============================================================

FAMILY_GENERIC_WORDS = {
    "eau",
    "de",
    "parfum",
    "perfume",
    "edp",
    "edt",
    "edc",
    "extrait",
    "spray",
    "toilette",
    "cologne",
    "for",
    "by",
    "men",
    "women",
    "man",
    "woman",
    "homme",
    "femme",
    "uomo",
    "donna",
    "unisex",
    "voor",
    "mannen",
    "dames",
    "pour",
    "lui",
    "lei",
    "ml",
    "cl",
}


def _family_core(value: Any, brand: str = "") -> str:
    text = norm(value)

    if not text:
        return ""

    brand_normalized = norm(brand)
    if brand_normalized:
        text = re.sub(
            rf"\b{re.escape(brand_normalized)}\b",
            " ",
            text,
        )

    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
        " ",
        text,
        flags=re.I,
    )

    tokens = [
        token
        for token in text.split()
        if token not in FAMILY_GENERIC_WORDS
        and not re.fullmatch(r"\d+(?:[.,]\d+)?", token)
    ]

    return " ".join(tokens).strip()


def _load_family_registry() -> Dict[str, Any]:
    errors = []

    for registry_path in FAMILY_REGISTRY_CANDIDATE_PATHS:
        try:
            with open(
                registry_path,
                "r",
                encoding="utf-8",
            ) as file:
                data = json.load(file)

            if isinstance(data, dict) and isinstance(data.get("families"), list):
                global FAMILY_REGISTRY_PATH
                FAMILY_REGISTRY_PATH = registry_path
                print(
                    f"FAMILY_REGISTRY_LOADED: {registry_path}",
                    flush=True,
                )
                return data

            errors.append(
                f"{registry_path}: invalid registry structure"
            )

        except Exception as exc:
            errors.append(
                f"{registry_path}: {type(exc).__name__}: {exc}"
            )

    print(
        "FAMILY_REGISTRY_LOAD_ERROR: " + " | ".join(errors),
        flush=True,
    )
    return {"families": []}


FAMILY_REGISTRY = _load_family_registry()


FAMILY_GENDER_ALIASES = {
    "men": "men",
    "man": "men",
    "male": "men",
    "him": "men",
    "homme": "men",
    "uomo": "men",
    "voor mannen": "men",
    "voor mennen": "men",
    "mannen": "men",
    "mennen": "men",
    "pour homme": "men",
    "for men": "men",
    "for him": "men",
    "women": "women",
    "woman": "women",
    "female": "women",
    "her": "women",
    "femme": "women",
    "donna": "women",
    "voor dames": "women",
    "dames": "women",
    "pour femme": "women",
    "for women": "women",
    "for her": "women",
    "unisex": "unisex",
    "unisexe": "unisex",
}


def _family_variant_signature(value: Any, brand: str = "") -> str:
    """Build a family-identity signature while preserving gender/variant markers."""
    text = norm(value)
    if not text:
        return ""

    brand_normalized = norm(brand)
    if brand_normalized:
        text = re.sub(
            rf"\b{re.escape(brand_normalized)}\b",
            " ",
            text,
        )

    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
        " ",
        text,
        flags=re.I,
    )

    # Normalize multi-word gender expressions before tokenization.
    gender_patterns = sorted(
        FAMILY_GENDER_ALIASES,
        key=lambda value: (-len(value.split()), -len(value)),
    )

    for phrase in gender_patterns:
        canonical = FAMILY_GENDER_ALIASES[phrase]
        text = re.sub(
            rf"\b{re.escape(phrase)}\b",
            f" {canonical} ",
            text,
            flags=re.I,
        )

    tokens = [
        token
        for token in text.split()
        if token not in {
            "eau",
            "de",
            "parfum",
            "perfume",
            "edp",
            "edt",
            "edc",
            "extrait",
            "spray",
            "toilette",
            "cologne",
            "by",
            "ml",
            "cl",
            "unknown",
            "not",
            "explicit",
            "default",
        }
        and not re.fullmatch(r"\d+(?:[.,]\d+)?", token)
    ]

    # Identity metadata is assembled from several independent fields. Remove
    # repeated tokens so a generic name plus a more specific source name does
    # not become an artificial identity such as "hawas hawas women".
    deduped = []
    seen = set()
    for token in tokens:
        if token in seen:
            continue
        seen.add(token)
        deduped.append(token)

    return " ".join(deduped).strip()


def _family_explicit_gender(value: Any) -> str:
    """Return an explicit audience marker found in structured product data."""
    text = norm(value)
    if not text:
        return ""

    # Longer phrases first so "for her" / "for him" are treated as one
    # audience marker rather than as generic words.
    if re.search(r"\b(?:for\s+her|for\s+women|pour\s+femme|pour\s+femmes|"
                 r"femme|femmes|woman|women|female|donna|dames)\b", text):
        return "women"

    if re.search(r"\b(?:for\s+him|for\s+men|pour\s+homme|pour\s+hommes|"
                 r"homme|hommes|man|men|male|uomo|mannen|mennen|voor\s+mannen)\b", text):
        return "men"

    if re.search(r"\b(?:unisex|unisexe|mixte)\b", text):
        return "unisex"

    return ""


def _product_explicit_gender(product: Dict[str, Any]) -> str:
    """Read explicit gender only from structured identity fields."""
    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        for key in ("gender", "audience", "sex", "target_gender"):
            value = attributes.get(key)
            if isinstance(value, dict):
                value = value.get("value")
            gender = _family_explicit_gender(value)
            if gender:
                return gender

    for key in ("gender", "audience", "sex", "target_gender"):
        gender = _family_explicit_gender(product.get(key))
        if gender:
            return gender

    source = product.get("source")
    if isinstance(source, dict):
        for key in ("source_name", "name", "title", "variant"):
            gender = _family_explicit_gender(source.get(key))
            if gender:
                return gender

    for key in ("name", "title", "product_name", "product_line", "variant"):
        gender = _family_explicit_gender(product.get(key))
        if gender:
            return gender

    return ""


def _family_products_for_gender(
    products: List[Any],
    gender: str,
) -> List[str]:
    """Return registry products whose aliases explicitly carry this gender."""
    matches = []

    if not gender:
        return matches

    gender_aliases = {
        "men": {"men"},
        "women": {"women"},
        "unisex": {"unisex"},
    }.get(gender, set())

    for item in products:
        if not isinstance(item, dict):
            continue

        canonical = str(item.get("canonical_name") or "").strip()
        if not canonical:
            continue

        aliases = list(item.get("aliases") or [])
        aliases.append(canonical)

        for alias in aliases:
            signature = _family_variant_signature(alias)
            signature_tokens = set(signature.split())
            if signature_tokens & gender_aliases:
                matches.append(canonical)
                break

    return matches


def _family_concentration(value: Any) -> str:
    text = norm(value)
    if re.search(r"\b(?:eau\s+de\s+parfum|edp)\b", text):
        return "edp"
    if re.search(r"\b(?:eau\s+de\s+toilette|edt)\b", text):
        return "edt"
    if re.search(r"\b(?:eau\s+de\s+cologne|edc)\b", text):
        return "edc"
    if re.search(r"\bextrait(?:\s+de\s+parfum)?\b", text):
        return "extrait"
    if re.search(r"\bparfum\b", text):
        return "parfum"
    return ""


def _family_alias_matches(
    query: str,
    alias: str,
    brand: str,
) -> bool:
    query_signature = _family_variant_signature(query, brand)
    alias_signature = _family_variant_signature(alias, brand)

    if not query_signature or query_signature != alias_signature:
        return False

    query_concentration = _family_concentration(query)
    if not query_concentration:
        return True

    alias_concentration = _family_concentration(alias)
    return alias_concentration == query_concentration


def _family_registry_candidates(
    query: str,
    product_brand: str,
) -> Optional[set]:
    query_signature = _family_variant_signature(
        query,
        product_brand,
    )

    if not query_signature:
        return None

    registry_families = FAMILY_REGISTRY.get("families", [])

    for family in registry_families:
        if not isinstance(family, dict):
            continue

        family_brand = str(
            family.get("brand") or ""
        ).strip()

        if product_brand and norm(product_brand) != norm(family_brand):
            continue

        family_aliases = family.get("query_aliases") or []
        products = family.get("products") or []

        # Exact product aliases take precedence over the generic family name.
        matched_products = set()
        for item in products:
            if not isinstance(item, dict):
                continue

            canonical = str(item.get("canonical_name") or "").strip()
            if not canonical:
                continue

            aliases = list(item.get("aliases") or [])
            aliases.append(canonical)

            if any(
                _family_alias_matches(query, alias, family_brand)
                for alias in aliases
            ):
                matched_products.add(canonical)

        if matched_products:
            return matched_products

        # A bare family query returns the whole verified family. If generic
        # concentration words are appended (e.g. "Hawas Eau de Parfum"), use
        # the family's explicit default product instead of mixing variants.
        family_match = any(
            query_signature == _family_variant_signature(alias, family_brand)
            for alias in family_aliases
        )

        if family_match:
            query_concentration = _family_concentration(query)
            if not query_concentration:
                return {
                    str(item.get("canonical_name") or "").strip()
                    for item in products
                    if isinstance(item, dict)
                    and str(item.get("canonical_name") or "").strip()
                }

            default_product = str(
                family.get("default_product") or ""
            ).strip()
            if default_product:
                return {default_product}

            return {
                str(item.get("canonical_name") or "").strip()
                for item in products
                if isinstance(item, dict)
                and str(item.get("canonical_name") or "").strip()
            }

    return None


def _family_registry_identity(
    product: Dict[str, Any],
    query: str = "",
) -> Optional[Dict[str, str]]:
    """Resolve a discovered product to one canonical registry identity."""
    product_brand = product_field(
        product,
        "brand",
        "source_brand",
    )

    source = product.get("source")
    if isinstance(source, dict) and not product_brand:
        product_brand = str(
            source.get("brand")
            or source.get("source_brand")
            or ""
        ).strip()

    # Identity is derived only from product naming/variant metadata.
    # URLs are deliberately excluded: retailer URLs often contain slugs,
    # tracking tokens or unrelated path words and must never change the
    # canonical family identity.
    identity_values = [
        product.get("name"),
        product.get("title"),
        product.get("product_name"),
        product.get("product_line"),
        product.get("variant"),
        product.get("gender"),
        product.get("audience"),
        product.get("sex"),
        product.get("target_gender"),
    ]

    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        for key in ("gender", "audience", "sex", "target_gender", "product_line"):
            value = attributes.get(key)
            if isinstance(value, dict):
                value = value.get("value")
            identity_values.append(value)

    source = product.get("source")
    if isinstance(source, dict):
        identity_values.extend([
            source.get("source_name"),
            source.get("name"),
            source.get("title"),
            source.get("product_line"),
            source.get("variant"),
            source.get("gender"),
            source.get("audience"),
        ])

    family_text = " ".join(
        str(value or "")
        for value in identity_values
    )

    # Some scrapers do not populate a dedicated brand field. Infer the brand
    # only when an exact registered brand is explicitly present in the
    # product identity text. This keeps the registry generic while allowing
    # valid retailer titles such as "Rasasi - Hawas Eau de Parfum".
    if not product_brand:
        family_text_normalized = norm(family_text)
        for registered_family in FAMILY_REGISTRY.get("families", []):
            if not isinstance(registered_family, dict):
                continue
            registered_brand = str(
                registered_family.get("brand") or ""
            ).strip()
            registered_brand_normalized = norm(registered_brand)
            if (
                registered_brand_normalized
                and re.search(
                    rf"\b{re.escape(registered_brand_normalized)}\b",
                    family_text_normalized,
                )
            ):
                product_brand = registered_brand
                break

    product_signature = _family_variant_signature(
        family_text,
        product_brand,
    )

    if not product_signature:
        return None

    for family in FAMILY_REGISTRY.get("families", []):
        if not isinstance(family, dict):
            continue

        family_brand = str(family.get("brand") or "").strip()
        if product_brand and norm(product_brand) != norm(family_brand):
            continue

        products = family.get("products") or []

        # A bare family name is ambiguous whenever the registry contains
        # gendered products. Never silently force it to a default product:
        # first use an explicit gender supplied by the retailer.
        family_aliases = family.get("query_aliases") or []
        generic_family_signatures = {
            _family_variant_signature(alias, family_brand)
            for alias in family_aliases
            if _family_variant_signature(alias, family_brand)
        }

        if product_signature in generic_family_signatures:
            explicit_gender = _product_explicit_gender(product)
            gender_products = _family_products_for_gender(
                products,
                explicit_gender,
            )

            if len(gender_products) == 1:
                return {
                    "family_id": str(family.get("family_id") or "").strip(),
                    "brand": family_brand,
                    "canonical_name": gender_products[0],
                }

            # If the retailer did not provide enough identity information,
            # reject the candidate instead of inventing an association.
            # This is essential for families such as Hawas where "Hawas"
            # can refer to both a men's and a women's product.
            if not explicit_gender or len(gender_products) != 1:
                # Some retailers expose the gender on the product page but
                # return only the generic product name in the scraper payload
                # (for example, a page titled simply "Hawas"). When the user
                # query explicitly identifies exactly one registered gendered
                # product, use that query as a tie-breaker for an otherwise
                # ambiguous generic candidate. A bare/ambiguous query never
                # gets this fallback.
                query_targets = (
                    _family_registry_candidates(query, family_brand)
                    if query
                    else None
                )

                if query_targets and len(query_targets) == 1:
                    query_target = next(iter(query_targets))
                    target_item = next(
                        (
                            item
                            for item in products
                            if isinstance(item, dict)
                            and str(item.get("canonical_name") or "").strip()
                            == query_target
                        ),
                        None,
                    )

                    if isinstance(target_item, dict):
                        target_aliases = list(
                            target_item.get("aliases") or []
                        )
                        target_aliases.append(query_target)

                        if any(
                            _family_explicit_gender(alias)
                            for alias in target_aliases
                        ):
                            return {
                                "family_id": str(
                                    family.get("family_id") or ""
                                ).strip(),
                                "brand": family_brand,
                                "canonical_name": query_target,
                            }

                return None

        matches = []
        product_concentration = _family_concentration(family_text)

        for item in products:
            if not isinstance(item, dict):
                continue

            canonical = str(item.get("canonical_name") or "").strip()
            if not canonical:
                continue

            aliases = list(item.get("aliases") or [])
            aliases.append(canonical)

            signature_matches = [
                alias
                for alias in aliases
                if product_signature == _family_variant_signature(
                    alias,
                    family_brand,
                )
            ]

            if not signature_matches:
                continue

            if product_concentration:
                concentration_matches = [
                    alias
                    for alias in signature_matches
                    if _family_concentration(alias) == product_concentration
                ]
                if concentration_matches:
                    matches.append(canonical)
                    continue

                # A canonical base product without an explicit concentration
                # remains eligible only when no concentration-specific alias
                # exists for the same identity.
                if any(_family_concentration(alias) for alias in signature_matches):
                    continue

            matches.append(canonical)

        if len(matches) == 1:
            return {
                "family_id": str(family.get("family_id") or "").strip(),
                "brand": family_brand,
                "canonical_name": matches[0],
            }

    return None


def _family_registry_accepts(
    product: Dict[str, Any],
    query: str,
) -> Optional[bool]:
    product_brand = product_field(
        product,
        "brand",
        "source_brand",
    )

    source = product.get("source")
    if isinstance(source, dict) and not product_brand:
        product_brand = str(
            source.get("brand")
            or source.get("source_brand")
            or ""
        ).strip()

    registry_target = _family_registry_candidates(
        query,
        product_brand,
    )

    if registry_target is None and not product_brand:
        registry_target = _family_registry_candidates(query, "")

    if registry_target is None:
        return None

    identity = _family_registry_identity(
        product,
        query,
    )
    if identity is None:
        return None

    return identity["canonical_name"] in registry_target

def price_num(value: Any) -> Optional[float]:
    match = re.search(
        r"(\d{1,5}(?:[.,]\d{1,2})?)",
        str(value or ""),
    )
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def product_image(product: Dict[str, Any]) -> str:
    source = product.get("source")
    source_image = source.get("image") if isinstance(source, dict) else None
    return (
        product.get("image")
        or product.get("image_url")
        or product.get("thumbnail")
        or source_image
        or ""
    )


def nested_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value")
    return value


def product_field(product: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = product.get(key)
        if value not in (None, ""):
            return str(nested_value(value)).strip()
    return ""


def identity_value(product: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = product.get(key)
        if value not in (None, ""):
            value = nested_value(value)
            if value not in (None, ""):
                return str(value).strip()

    identity = product.get("identity")
    if isinstance(identity, dict):
        for key in keys:
            value = nested_value(identity.get(key))
            if value not in (None, ""):
                return str(value).strip()

    return ""


def product_size_ml(product: Dict[str, Any]) -> Optional[float]:
    explicit = (
        product.get("size_ml")
        or product.get("volume_ml")
        or product.get("format_ml")
    )
    explicit = nested_value(explicit)

    if explicit not in (None, ""):
        try:
            return float(str(explicit).replace(",", "."))
        except (TypeError, ValueError):
            pass

    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        for key in ("size_ml", "volume_ml", "format_ml"):
            value = nested_value(attributes.get(key))
            if value not in (None, ""):
                try:
                    return float(str(value).replace(",", "."))
                except (TypeError, ValueError):
                    pass

    source = product.get("source")
    source_name = source.get("source_name") if isinstance(source, dict) else ""

    text = " ".join(
        str(product.get(key) or "")
        for key in (
            "name",
            "title",
            "product_name",
            "size",
            "format",
            "volume",
        )
    )
    text += " " + str(source_name or "")

    match = re.search(
        r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
        re.I,
    )
    if not match:
        return None

    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None

    if match.group(2).lower() == "cl":
        value *= 10

    return value


def product_concentration(product: Dict[str, Any]) -> str:
    value = product_field(product, "concentration")
    if value:
        return norm(value)

    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        value = nested_value(attributes.get("concentration"))
        if value:
            return norm(value)

    text = " ".join(
        str(product.get(key) or "")
        for key in ("name", "title", "product_name")
    )
    text = norm(text)

    for label, pattern in (
        ("extrait de parfum", r"\bextrait(?: de)? parfum\b"),
        ("eau de parfum", r"\beau de parfum\b|\bedp\b"),
        ("eau de toilette", r"\beau de toilette\b|\bedt\b"),
        ("eau de cologne", r"\beau de cologne\b|\bedc\b"),
        ("parfum", r"\bparfum\b"),
    ):
        if re.search(pattern, text, re.I):
            return label

    return ""


def product_availability(product: Dict[str, Any]) -> str:
    offer = product.get("offer")
    if isinstance(offer, dict):
        value = offer.get("availability")
        if value:
            return norm(value)

    value = product.get("availability")
    if value:
        return norm(value)

    if "available" in product:
        available = product.get("available")
        if available is True:
            return "in stock"
        if available is False:
            return "out of stock"

    return "unknown"


def product_search_text(product: Dict[str, Any]) -> str:
    values = [
        product.get("name"),
        product.get("title"),
        product.get("product_name"),
        product.get("brand"),
        product.get("source_brand"),
        product.get("url"),
        product.get("product_line"),
        product.get("variant"),
        product.get("size"),
        product.get("size_ml"),
        product.get("volume"),
        product.get("volume_ml"),
        product.get("format"),
        product.get("format_ml"),
        product.get("pack_size"),
    ]

    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        for value in attributes.values():
            values.append(nested_value(value))

    source = product.get("source")
    if isinstance(source, dict):
        values.extend(
            [
                source.get("source_name"),
                source.get("source_brand"),
                source.get("name"),
                source.get("brand"),
            ]
        )

    return norm(" ".join(str(value or "") for value in values))


def has_small_size(product: Dict[str, Any]) -> bool:
    size = product_size_ml(product)
    if size is not None:
        return size <= 10

    text = product_search_text(product)
    for match in re.finditer(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b",
        text,
    ):
        try:
            if float(match.group(1).replace(",", ".")) <= 10:
                return True
        except ValueError:
            continue

    return False


# ============================================================
# VALIDAZIONE
# ============================================================

def matches(product: Dict[str, Any], query: str) -> bool:
    query_normalized = norm(query)

    if not query_normalized:
        return False

    name = product_field(
        product,
        "name",
        "title",
        "product_name",
    )

    brand = product_field(
        product,
        "brand",
        "source_brand",
    )

    source = product.get("source")

    if isinstance(source, dict):
        if not brand:
            brand = str(
                source.get("brand")
                or source.get("source_brand")
                or ""
            ).strip()

        if not name:
            name = str(
                source.get("name")
                or source.get("title")
                or ""
            ).strip()

    name_normalized = norm(name)

    if not name_normalized:
        return False

    query_has_size = bool(
        re.search(
            r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
            query_normalized,
        )
    )

    if has_small_size(product) and not query_has_size:
        return False

    for phrase in NON_PERFUME:
        phrase_normalized = norm(phrase)

        if (
            phrase_normalized in name_normalized
            and phrase_normalized not in query_normalized
        ):
            return False

    family_registry_decision = _family_registry_accepts(
        product,
        query,
    )

    if family_registry_decision is False:
        return False

    # The family registry is authoritative when it can resolve the candidate
    # to the exact product requested. This is important when a retailer's
    # scraped title is generic (e.g. "Hawas") while the search query carries
    # the decisive variant such as "for him" or "for her".
    if family_registry_decision is True:
        return True

    name_for_matching = name_normalized

    name_for_matching = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
        " ",
        name_for_matching,
        flags=re.I,
    )

    name_for_matching = re.sub(
        r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|"
        r"eau\s+de\s+cologne|extrait\s+de\s+parfum|"
        r"edp|edt|edc)\b",
        " ",
        name_for_matching,
        flags=re.I,
    )

    name_for_matching = re.sub(
        r"\s+",
        " ",
        name_for_matching,
    ).strip()

    query_tokens = [
        token
        for token in query_normalized.split()
        if token not in IGNORED_WORDS
        and not re.fullmatch(
            r"\d+(?:[.,]\d+)?",
            token,
        )
    ]

    generic_tokens = {
        "eau",
        "de",
        "parfum",
        "perfume",
        "edp",
        "edt",
        "edc",
        "extrait",
        "spray",
        "intense",
        "limited",
        "edition",
        "for",
        "men",
        "women",
        "homme",
        "femme",
        "unisex",
    }

    family_tokens = [
        token
        for token in query_tokens
        if token not in generic_tokens
    ]

    if not family_tokens:
        family_tokens = query_tokens

    if not family_tokens:
        return False

    name_tokens = name_for_matching.split()

    family_phrase = " ".join(family_tokens)
    name_phrase = " ".join(
        token
        for token in name_tokens
        if token not in generic_tokens
    )

    if not family_phrase or not name_phrase:
        return False

    padded_name = f" {name_phrase} "
    padded_family = f" {family_phrase} "

    return padded_family in padded_name


# ============================================================
# DISCOVERY GENERICA
# ============================================================

def build_search_attempts(store: str, query: str) -> List[str]:
    """
    Costruisce una sequenza corta e deterministica di query generiche,
    ordinate dalla più precisa alla più permissiva.

    Il parametro store resta nella firma per compatibilità con il codice
    esistente, ma NON modifica le strategie in base al negozio.
    """
    del store

    raw = str(query or "").strip()
    normalized = norm(raw)

    if not raw or not normalized:
        return []

    attempts: List[str] = []
    seen = set()

    def add(value: str) -> None:
        value = str(value or "").strip()
        key = norm(value)
        if value and key and key not in seen:
            seen.add(key)
            attempts.append(value)

    # 1) Query originale: è sempre la discovery più precisa.
    add(raw)

    # 2) Query normalizzata senza parole puramente descrittive.
    tokens = [
        token
        for token in normalized.split()
        if token not in IGNORED_WORDS
    ]

    if tokens:
        add(" ".join(tokens))

    # 3) Forma compatta per siti che indicizzano "100ml" e "100 ml"
    #    come stringhe diverse.
    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )
    add(compact)

    return attempts


# ============================================================
# PREZZO
# ============================================================

def _price_from_structured_html(html: str) -> Optional[float]:
    html = html or ""

    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )

    def walk(value):
        if isinstance(value, dict):
            offers = value.get("offers")

            if isinstance(offers, dict):
                for key in ("price", "lowPrice"):
                    value_price = price_num(offers.get(key))
                    if value_price is not None:
                        yield value_price

            elif isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        for key in ("price", "lowPrice"):
                            value_price = price_num(offer.get(key))
                            if value_price is not None:
                                yield value_price

            for child in value.values():
                yield from walk(child)

        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for raw in scripts:
        try:
            payload = json.loads(raw.strip())
        except Exception:
            continue

        prices = list(walk(payload))
        if prices:
            return prices[0]

    patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            value_price = price_num(match.group(1))
            if value_price is not None:
                return value_price

    return None


def resolve_actual_price(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Corregge il caso generico in cui il prezzo esposto dal risultato
    sia esplicitamente un prezzo unitario per 100 ml.

    Non apre la pagina prodotto se il prezzo è già un prezzo di vendita
    normale. In questo modo la fase centrale non trasforma una discovery
    con molti risultati in una sequenza di richieste aggiuntive.
    """
    item = dict(product)
    raw_price = str(item.get("price") or "").strip()
    size = product_size_ml(item)

    unit_match = re.search(
        r"(?:/|per\s*)100\s*ml",
        raw_price,
        re.I,
    )

    if unit_match and size and size > 0:
        unit = price_num(raw_price[:unit_match.start()])

        if unit is not None:
            actual = round(unit * size / 100.0, 2)
            item["price"] = f"{actual:.2f} €"
            item["price_value"] = actual

    return item


# ============================================================
# IDENTITA / DEDUPLICAZIONE
# ============================================================

def product_identity_key(
    product: Dict[str, Any],
) -> tuple:
    canonical = norm(
        product.get("product_identity")
        or ""
    )

    if canonical:
        return (
            "catalog",
            canonical,
        )

    family_id = norm(
        product.get("family_id")
        or product.get("product_id")
        or product.get("catalog_id")
        or ""
    )

    variant = norm(
        product.get("catalog_variant")
        or product.get("canonical_name")
        or product.get("product_line")
        or product.get("name")
        or ""
    )

    concentration = norm(
        product.get("concentration")
        or ""
    )

    return (
        "catalog",
        family_id,
        variant,
        concentration,
    )


def unique_results(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique: List[Dict[str, Any]] = []
    seen = set()

    for product in products:
        key = product_identity_key(product)

        if key in seen:
            continue

        seen.add(key)
        unique.append(product)

    return unique


def deterministic_result_key(product: Dict[str, Any]) -> tuple:
    store = norm(product.get("store", ""))
    price = price_num(product.get("price"))

    if price is None:
        price_key = float("inf")
    else:
        price_key = round(price, 4)

    name = norm(
        product_field(
            product,
            "name",
            "title",
            "product_name",
        )
    )

    url = str(product.get("url") or "").strip().lower()

    availability = product_availability(product)

    availability_rank = {
        "in stock": 0,
        "in_stock": 0,
        "available": 0,
        "out of stock": 1,
        "out_of_stock": 1,
        "unknown": 2,
    }.get(availability, 3)

    store_rank = (
        STORES.index(store)
        if store in STORES
        else len(STORES)
    )

    return (
        price_key,
        availability_rank,
        store_rank,
        name,
        url,
    )


def sort_by_price(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        products,
        key=deterministic_result_key,
    )


# ============================================================
# SCRAPER
# ============================================================

def load_scraper(store: str):
    return importlib.import_module(
        f"scrapers.{store}.scraper"
    )


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    """
    Esegue SOLO la discovery generica dello store.

    Il risultato di questa funzione è un candidate pool grezzo:
    la validazione centrale viene eseguita dall'orchestratore dopo
    che tutti gli store hanno avuto la possibilità di contribuire.

    Nessuna regola di matching viene applicata qui.
    """
    module = load_scraper(store)

    search_fn = getattr(module, "search", None)

    if not callable(search_fn):
        search_fn = getattr(module, "scrape", None)

    if not callable(search_fn):
        raise RuntimeError(
            f"{store}: scraper senza funzione search()/scrape()"
        )

    discovery_query = norm(query)

    attempts = build_search_attempts(
        store,
        discovery_query,
    )

    output: List[Dict[str, Any]] = []
    seen = set()

    for attempt in attempts:
        try:
            results = search_fn(attempt) or []
        except Exception as exc:
            print(
                f"STORE_DISCOVERY_ERROR: store={store} "
                f"attempt={attempt!r} error={type(exc).__name__}: {exc}",
                flush=True,
            )
            continue

        if not isinstance(results, list):
            continue

        for item in results:
            if not isinstance(item, dict):
                continue

            product = dict(item)
            product.setdefault("store", store)

            product = resolve_actual_price(product)

            image = product_image(product)
            if image:
                product["image"] = image

            key = product_identity_key(product)

            if key in seen:
                continue

            seen.add(key)
            output.append(product)

    return output


# ============================================================
# CENTRAL ORCHESTRATOR
# ============================================================

def _candidate_relevance_score(
    product: Dict[str, Any],
    query: str,
) -> tuple:
    """
    Ranking preliminare NON distruttivo.

    Serve solo a stabilire l'ordine con cui i candidati vengono validati.
    Non elimina candidati: la validazione centrale decide esclusivamente
    tramite matches().
    """
    query_tokens = [
        token
        for token in norm(query).split()
        if token not in IGNORED_WORDS
        and not re.fullmatch(r"\d+(?:[.,]\d+)?", token)
    ]

    name = norm(
        product_field(
            product,
            "name",
            "title",
            "product_name",
        )
    )

    brand = norm(
        product_field(
            product,
            "brand",
            "source_brand",
        )
    )

    name_tokens = set(name.split())
    brand_tokens = set(brand.split())

    matched_name = sum(
        1 for token in query_tokens
        if token in name_tokens
    )

    matched_text = sum(
        1 for token in query_tokens
        if token in name
    )

    matched_brand = sum(
        1 for token in query_tokens
        if token in brand_tokens
    )

    return (
        -matched_name,
        -matched_text,
        -matched_brand,
        deterministic_result_key(product),
    )


def _pre_rank_candidates(
    candidates: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    return sorted(
        candidates,
        key=lambda product: _candidate_relevance_score(
            product,
            query,
        ),
    )


def _catalog_image_matches_identity(
    product: Dict[str, Any],
    identity: Dict[str, str],
) -> bool:
    """
    Verifica che l'immagine associata a un'offerta sia compatibile con la
    variante canonica assegnata dal Family Registry.

    Il registry può correggere/normalizzare l'identità commerciale di un
    candidato, ma non deve permettere che un'immagine appartenente a una
    variante sorella venga trascinata sul risultato normalizzato.

    La verifica è completamente generica: confronta i token distintivi delle
    varianti presenti nella famiglia con quelli presenti nell'URL/nome
    dell'immagine. Se l'immagine identifica chiaramente una variante diversa,
    l'immagine viene rimossa; l'offerta, il prezzo e l'URL restano invariati.
    """
    image = product_image(product)
    if not image:
        return True

    family_id = str(identity.get("family_id") or "").strip()
    target_name = str(identity.get("canonical_name") or "").strip()
    brand = str(identity.get("brand") or "").strip()

    if not family_id or not target_name:
        return True

    family = next(
        (
            item
            for item in FAMILY_REGISTRY.get("families", [])
            if isinstance(item, dict)
            and str(item.get("family_id") or "").strip() == family_id
        ),
        None,
    )
    if not isinstance(family, dict):
        return True

    def identity_tokens(value: Any) -> set:
        text = _family_core(value, brand)
        return {
            token
            for token in text.split()
            if len(token) >= 3
        }

    target_tokens = identity_tokens(target_name)
    image_tokens = identity_tokens(str(image))

    if not target_tokens or not image_tokens:
        return True

    products = family.get("products") or []

    for item in products:
        if not isinstance(item, dict):
            continue

        sibling_name = str(item.get("canonical_name") or "").strip()
        if not sibling_name or norm(sibling_name) == norm(target_name):
            continue

        sibling_tokens = identity_tokens(sibling_name)
        if not sibling_tokens:
            continue

        # The image explicitly identifies a different sibling variant while
        # the assigned canonical variant is absent from the image identity.
        if sibling_tokens.issubset(image_tokens) and not target_tokens.issubset(image_tokens):
            return False

        # Also catch the inverse case where the target has no additional
        # distinguishing token (e.g. base product) and the image explicitly
        # names a more specific sibling variant.
        sibling_extra = sibling_tokens - target_tokens
        target_extra = target_tokens - sibling_tokens
        if (
            sibling_extra
            and sibling_extra.issubset(image_tokens)
            and not target_extra.intersection(image_tokens)
        ):
            return False

    return True


def _validate_candidate(
    product: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    if not matches(product, query):
        return None

    identity = _family_registry_identity(
        product,
        query,
    )
    if identity is not None:
        normalized_product = dict(product)
        original_name = product_field(
            product,
            "name",
            "title",
            "product_name",
        )

        # Preserve the retailer wording for diagnostics while exposing one
        # canonical identity to the frontend/grouping layer.
        if original_name:
            normalized_product["source_name"] = original_name
            normalized_product.setdefault("_source_name", original_name)

        normalized_product["family_id"] = identity["family_id"]
        normalized_product["canonical_name"] = identity["canonical_name"]
        normalized_product["brand"] = identity["brand"]

        # The Family Registry may normalize a retailer candidate to a
        # canonical variant. Never keep an image that clearly belongs to a
        # different sibling variant in the same family.
        if not _catalog_image_matches_identity(product, identity):
            normalized_product["image"] = ""
            normalized_product["image_url"] = ""
            normalized_product["thumbnail"] = ""
            source = normalized_product.get("source")
            if isinstance(source, dict):
                source = dict(source)
                source["image"] = ""
                source["image_url"] = ""
                source["thumbnail"] = ""
                normalized_product["source"] = source

        return normalized_product

    return product


def _validate_candidates_parallel(
    candidates: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    max_workers = min(
        32,
        max(1, len(candidates)),
    )

    with ThreadPoolExecutor(
        max_workers=max_workers,
        thread_name_prefix="scent_validate",
    ) as executor:
        futures = [
            executor.submit(
                _validate_candidate,
                product,
                query,
            )
            for product in candidates
        ]

        validated: List[Dict[str, Any]] = []

        for future in futures:
            try:
                product = future.result()
            except Exception as exc:
                print(
                    "CENTRAL_VALIDATION_ERROR: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )
                continue

            if isinstance(product, dict):
                validated.append(product)

    return validated


def _orchestrate_results(
    candidates: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    """
    Pipeline centrale:

        candidate pool
        -> deduplica
        -> pre-ranking
        -> validazione parallela
        -> deduplica finale
        -> ranking finale
    """
    candidate_pool = unique_results(candidates)

    ranked_candidates = _pre_rank_candidates(
        candidate_pool,
        query,
    )

    validated = _validate_candidates_parallel(
        ranked_candidates,
        query,
    )

    return sort_by_price(
        unique_results(validated)
    )

# ============================================================
# SEARCH CENTRALE
# ==================================================

def search_perfume(query: str) -> Dict[str, Any]:
    query = str(query or "").strip()

    if not query:
        return {
            "query": "",
            "count": 0,
            "results": [],
            "comparisons": [],
            "errors": {},
        }

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    executor = ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="scent_store",
    )

    futures = {
        executor.submit(run_store, store, query): store
        for store in STORES
    }

    try:
        try:
            completed = as_completed(
                futures,
                timeout=GLOBAL_SEARCH_TIMEOUT,
            )

            for future in completed:
                store = futures[future]

                try:
                    store_results = future.result()
                    if isinstance(store_results, list):
                        all_results.extend(store_results)

                except Exception as exc:
                    errors[store] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    traceback.print_exc()

        except TimeoutError:
            for future, store in futures.items():
                if future.done():
                    try:
                        store_results = future.result()
                        if isinstance(store_results, list):
                            all_results.extend(store_results)

                    except Exception as exc:
                        errors[store] = (
                            f"{type(exc).__name__}: {exc}"
                        )
                        traceback.print_exc()
                else:
                    errors[store] = (
                        "Timeout: ricerca del negozio oltre il limite globale"
                    )

    finally:
        for future, store in futures.items():
            if not future.done():
                future.cancel()

        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )

    # ← FIX: usa _orchestrate_results() per applicare matches()
    results = _orchestrate_results(
        all_results,
        query,
    )

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "comparisons": [],
        "errors": errors,
    }
    
# ============================================================
# PRICE HISTORY
# ============================================================

def load_history() -> Dict[str, Any]:
    try:
        with open(
            HISTORY_PATH,
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        if isinstance(data, dict):
            return data

    except Exception:
        pass

    return {}


def save_history(
    data: Dict[str, Any],
) -> None:
    try:
        with open(
            HISTORY_PATH,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

    except OSError:
        pass


def update_price_history(
    name: str,
    brand: str,
    best_offer: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    history_data = load_history()

    key = (
        norm(f"{brand} {name}")
        or norm(name)
    )

    history = history_data.get(
        key,
        [],
    )

    if not isinstance(history, list):
        history = []

    if not best_offer:
        return history

    price_value = price_num(
        best_offer.get("price")
    )

    if price_value is None:
        return history

    point = {
        "date": datetime.now(
            timezone.utc
        ).isoformat(),
        "value": price_value,
        "price": best_offer.get(
            "price",
            "",
        ),
        "store": best_offer.get(
            "store",
            "",
        ),
    }

    last = (
        history[-1]
        if history
        else None
    )

    changed = (
        not last
        or last.get("value") != point["value"]
        or last.get("store") != point["store"]
    )

    if changed:
        history.append(point)
        history = history[-100:]
        history_data[key] = history
        save_history(history_data)

    return history


# ============================================================
# API
# ============================================================


@app.get(
    "/",
    include_in_schema=False,
)
def root():
    if not FRONTEND_INDEX.exists():
        raise HTTPException(
            status_code=500,
            detail="frontend/index.html non trovato",
        )

    return FileResponse(
        FRONTEND_INDEX
    )


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "stores": STORES,
    }
    
# ============================================================
# ASYNC SEARCH JOBS
# ============================================================


SEARCH_JOBS = {}
SEARCH_JOBS_LOCK = threading.Lock()


def _search_job_snapshot(job_id: str) -> Dict[str, Any]:
    with SEARCH_JOBS_LOCK:
        job = SEARCH_JOBS.get(job_id)

        if job is None:
            raise HTTPException(
                status_code=404,
                detail="Job di ricerca non trovato",
            )

        results = sort_by_price(
            unique_results(
                list(job["results"])
            )
        )

        return {
            "job_id": job_id,
            "query": job["query"],
            "count": len(results),
            "results": results,
            "comparisons": [],
            "errors": dict(job["errors"]),
            "completed": job["completed"],
            "status": (
                "completed"
                if job["completed"]
                else "searching"
            ),
        }


def _run_search_job(
    job_id: str,
    query: str,
) -> None:
    """
    Esegue la discovery in parallelo e alimenta progressivamente
    il candidate pool centrale.

    Ogni volta che uno store termina:
        discovery -> candidate pool -> deduplica -> pre-ranking
        -> validazione centrale parallela -> risultati parziali.
    """
    executor = ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="scent_async_store",
    )

    futures = {
        executor.submit(
            run_store,
            store,
            query,
        ): store
        for store in STORES
    }

    def process_store_candidates(
        store: str,
        store_candidates: Any,
    ) -> None:
        if not isinstance(store_candidates, list):
            return

        with SEARCH_JOBS_LOCK:
            job = SEARCH_JOBS.get(job_id)

            if job is None:
                return

            job["candidates"].extend(
                store_candidates
            )

            candidate_pool = list(
                job["candidates"]
            )

        results = _orchestrate_results(
            candidate_pool,
            query,
        )

        with SEARCH_JOBS_LOCK:
            job = SEARCH_JOBS.get(job_id)

            if job is not None:
                job["results"] = results

    try:
        try:
            for future in as_completed(
                futures,
                timeout=GLOBAL_SEARCH_TIMEOUT,
            ):
                store = futures[future]

                try:
                    store_candidates = future.result()

                    process_store_candidates(
                        store,
                        store_candidates,
                    )

                except Exception as exc:
                    with SEARCH_JOBS_LOCK:
                        job = SEARCH_JOBS.get(job_id)

                        if job is not None:
                            job["errors"][store] = (
                                f"{type(exc).__name__}: {exc}"
                            )

        except TimeoutError:
            for future, store in futures.items():
                if future.done():
                    try:
                        store_candidates = future.result()

                        process_store_candidates(
                            store,
                            store_candidates,
                        )

                    except Exception as exc:
                        with SEARCH_JOBS_LOCK:
                            job = SEARCH_JOBS.get(job_id)

                            if job is not None:
                                job["errors"][store] = (
                                    f"{type(exc).__name__}: {exc}"
                                )

                else:
                    with SEARCH_JOBS_LOCK:
                        job = SEARCH_JOBS.get(job_id)

                        if job is not None:
                            job["errors"][store] = (
                                "Timeout: ricerca del negozio "
                                "oltre il limite globale"
                            )

    finally:
        for future in futures:
            if not future.done():
                future.cancel()

        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )

        with SEARCH_JOBS_LOCK:
            job = SEARCH_JOBS.get(job_id)

            if job is not None:
                job["completed"] = True


@app.get("/search-start")
def search_start(q: str):
    query = str(q or "").strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Parametro q mancante",
        )

    job_id = uuid.uuid4().hex

    with SEARCH_JOBS_LOCK:
        SEARCH_JOBS[job_id] = {
            "query": query,
            "candidates": [],
            "results": [],
            "errors": {},
            "completed": False,
        }

    thread = threading.Thread(
        target=_run_search_job,
        args=(job_id, query),
        daemon=True,
    )

    thread.start()

    return {
        "job_id": job_id,
        "query": query,
        "count": 0,
        "results": [],
        "comparisons": [],
        "errors": {},
        "completed": False,
        "status": "searching",
    }


@app.get("/search-status")
def search_status(job_id: str):
    return _search_job_snapshot(job_id)


@app.get("/search")
def search(q: str):
    return search_perfume(q)


@app.get("/routing")
def routing(q: str):
    return {
        "query": str(q or "").strip(),
        "stores": list(STORES),
    }


@app.get("/test-store")
def test_store(
    store: str,
    q: str,
):
    store = str(store or "").strip().lower()
    query = str(q or "").strip()

    if store not in STORES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Store non valido. Disponibili: "
                + ", ".join(STORES)
            ),
        )

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Parametro q mancante",
        )

    try:
        results = run_store(
            store,
            query,
        )

        return {
            "store": store,
            "query": query,
            "count": len(results),
            "results": sort_by_price(
                unique_results(results)
            ),
        }

    except Exception as error:
        traceback.print_exc()

        return {
            "store": store,
            "query": query,
            "count": 0,
            "results": [],
            "error": (
                f"{type(error).__name__}: {error}"
            ),
        }


# ============================================================
# SUGGEST
# ============================================================

def fragella_search(
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    api_key = os.getenv(
        "FRAGELLA_API_KEY",
        "",
    ).strip()

    if not api_key:
        return []

    params = urlencode(
        {
            "search": query,
            "limit": max(
                1,
                min(int(limit), 10),
            ),
        }
    )

    request = Request(
        "https://api.fragella.com/api/v1/fragrances?"
        + params,
        headers={
            "x-api-key": api_key,
            "Accept": "application/json",
            "User-Agent": "ScentHunter/1.0",
        },
    )

    with urlopen(
        request,
        timeout=5,
    ) as response:
        payload = json.loads(
            response.read().decode(
                "utf-8"
            )
        )

    if isinstance(payload, dict):
        items = (
            payload.get("data")
            or payload.get("results")
            or payload.get("fragrances")
            or []
        )

    elif isinstance(payload, list):
        items = payload

    else:
        items = []

    output: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        name = str(
            item.get("Name")
            or item.get("name")
            or ""
        ).strip()

        brand = str(
            item.get("Brand")
            or item.get("brand")
            or ""
        ).strip()

        image = str(
            item.get("Image URL Transparent")
            or item.get("Image URL")
            or item.get("image")
            or ""
        ).strip()

        if not name:
            continue

        output.append(
            {
                "name": name,
                "brand": brand,
                "store": brand or "ScentHunter",
                "image": image,
                "catalog_id": (
                    item.get("_id")
                    or item.get("id")
                ),
            }
        )

    return output


def rank_catalog_suggestions(
    items: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    query_n = norm(query)

    tokens = [
        token
        for token in query_n.split()
        if len(token) >= 2
    ]

    ranked = []
    seen = set()

    for item in items:
        name = str(
            item.get("name")
            or ""
        ).strip()

        brand = str(
            item.get("brand")
            or ""
        ).strip()

        if not name:
            continue

        name_n = norm(name)
        brand_n = norm(brand)
        text = norm(
            f"{brand} {name}"
        )

        if tokens and not all(
            token in text
            for token in tokens
        ):
            continue

        if any(
            norm(phrase) in name_n
            for phrase in NON_PERFUME
        ):
            continue

        key = (
            str(
                item.get("catalog_id")
                or ""
            ).strip()
            or f"{brand_n}|{name_n}"
        )

        if key in seen:
            continue

        seen.add(key)

        if name_n.startswith(query_n):
            priority = 0
        elif brand_n.startswith(query_n):
            priority = 1
        elif query_n in name_n:
            priority = 2
        elif query_n in brand_n:
            priority = 3
        else:
            priority = 4

        position = text.find(query_n)
        if position < 0:
            position = 999

        ranked.append(
            (
                priority,
                position,
                len(name_n),
                name_n,
                item,
            )
        )

    ranked.sort(
        key=lambda row: row[:4]
    )

    return [
        row[4]
        for row in ranked[:8]
    ]


@app.get("/suggest")
def suggest(q: str):
    raw_query = str(q or "").strip()
    query = norm(raw_query)

    if len(query) < 2:
        return {
            "query": q,
            "count": 0,
            "suggestions": [],
            "source": "catalog",
        }

    try:
        catalog_results: List[
            Dict[str, Any]
        ] = []

        catalog_seen = set()

        for item in fragella_search(
            raw_query,
            10,
        ):
            key = (
                str(
                    item.get("catalog_id")
                    or ""
                ).strip()
                or (
                    f"{norm(item.get('brand'))}|"
                    f"{norm(item.get('name'))}"
                )
            )

            if key in catalog_seen:
                continue

            catalog_seen.add(key)
            catalog_results.append(item)

        suggestions = rank_catalog_suggestions(
            catalog_results,
            raw_query,
        )

        return {
            "query": q,
            "count": len(suggestions),
            "suggestions": suggestions[:8],
            "source": "catalog",
        }

    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
    ) as error:
        print(
            "Catalog suggest error:",
            repr(error),
        )

    except Exception:
        traceback.print_exc()

    return {
        "query": q,
        "count": 0,
        "suggestions": [],
        "source": "catalog",
    }


@app.get("/autocomplete")
def autocomplete(q: str):
    return suggest(q)


# ============================================================
# PRODUCT
# ============================================================

@app.get("/product")
def product(
    name: str,
    brand: str = "",
):
    data = search_perfume(name)

    offers: List[
        Dict[str, Any]
    ] = []

    for product_data in data["results"]:
        value = price_num(
            product_data.get("price")
        )

        if value is None:
            continue

        offer = dict(product_data)
        offer["price_value"] = value
        offer["image"] = product_image(
            offer
        )

        offers.append(offer)

    offers.sort(
        key=lambda offer: (
            offer["price_value"],
            norm(offer.get("store", "")),
            norm(offer.get("name", "")),
            str(offer.get("url", "")).lower(),
        )
    )

    best_offer = (
        offers[0]
        if offers
        else None
    )

    history = update_price_history(
        name=name,
        brand=brand,
        best_offer=best_offer,
    )

    image = next(
        (
            offer["image"]
            for offer in offers
            if offer.get("image")
        ),
        "",
    )

    lowest_price = (
        best_offer.get("price")
        if best_offer
        else None
    )

    return {
        "name": name,
        "brand": brand,
        "image": image,
        "lowest_price": lowest_price,
        "best_offer": best_offer,
        "offers": offers,
        "history": history,
        "errors": data["errors"],
        "message": (
            ""
            if offers
            else "Nessuna offerta disponibile al momento"
        ),
    }


# ============================================================
# TEMPORARY NOTINO DIAGNOSTIC
# Remove this entire section after testing.
# ============================================================

@app.get("/diagnose-notino-module")
def diagnose_notino_module():
    try:
        module = importlib.import_module("scrapers.notino.scraper")

        return {
            "ok": True,
            "store": "notino",
            "module": module.__name__,
            "file": getattr(module, "__file__", None),
            "has_search": callable(getattr(module, "search", None)),
            "has_scrape": callable(getattr(module, "scrape", None)),
            "has_diagnose": callable(getattr(module, "diagnose", None)),
            "has_internal_search": callable(
                getattr(module, "_search_internal", None)
            ),
            "has_browser_discover": callable(
                getattr(module, "browser_discover", None)
            ),
            "has_http_discovery": callable(
                getattr(module, "_search_http_candidates", None)
            ),
            "has_candidate_extractor": callable(
                getattr(module, "extract_candidates_from_html", None)
            ),
        }

    except Exception as exc:
        return {
            "ok": False,
            "store": "notino",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


@app.get("/diagnose-notino")
def diagnose_notino(q: str):
    query = str(q or "").strip()

    if not query:
        return {
            "ok": False,
            "store": "notino",
            "error": "empty_query",
        }

    try:
        module = importlib.import_module("scrapers.notino.scraper")
        diagnose_fn = getattr(module, "diagnose", None)

        if not callable(diagnose_fn):
            return {
                "ok": False,
                "store": "notino",
                "query": query,
                "error": "Notino scraper has no diagnose() function",
            }

        return {
            "ok": True,
            "store": "notino",
            "query": query,
            "diagnostic": diagnose_fn(query),
        }

    except Exception as exc:
        return {
            "ok": False,
            "store": "notino",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


@app.get("/diagnose-notino-search")
def diagnose_notino_search(q: str):
    query = str(q or "").strip()

    if not query:
        return {
            "ok": False,
            "store": "notino",
            "error": "empty_query",
        }

    try:
        module = importlib.import_module("scrapers.notino.scraper")
        debug_fn = getattr(module, "debug_search", None)

        if not callable(debug_fn):
            return {
                "ok": False,
                "store": "notino",
                "query": query,
                "error": "Notino scraper has no debug_search() function",
            }

        return {
            "ok": True,
            "store": "notino",
            **debug_fn(query),
        }

    except Exception as exc:
        return {
            "ok": False,
            "store": "notino",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
