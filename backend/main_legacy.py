from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json

from product_matcher import ProductMatcher
import os
import re
import threading
import traceback
import time
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
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

BASE_DIR = Path(__file__).resolve().parent
HISTORY_PATH = BASE_DIR / "price_history.json"
PRODUCT_CATALOG_PATH = BASE_DIR / "product_catalog.json"
FAMILY_REGISTRY_PATH = BASE_DIR / "family_registry.json"


def _load_product_matcher_catalog() -> List[Dict[str, Any]]:
    """
    Adatta il catalogo autorevole ScentHunter v2 allo schema input
    del ProductMatcher centrale, senza duplicare regole di matching.
    """
    try:
        with open(PRODUCT_CATALOG_PATH, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except Exception as exc:
        print(
            "PRODUCT_MATCHER_CATALOG_LOAD_ERROR:",
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return []

    products = payload.get("products", []) if isinstance(payload, dict) else []
    variants = payload.get("variants", []) if isinstance(payload, dict) else []

    if not isinstance(products, list):
        return []
    if not isinstance(variants, list):
        variants = []

    by_product_id: Dict[str, Dict[str, Any]] = {}

    for variant in variants:
        if not isinstance(variant, dict):
            continue
        product_id = str(variant.get("product_id") or "").strip()
        if not product_id:
            continue
        target = by_product_id.setdefault(
            product_id,
            {"formats_ml": [], "gtins": [], "mpns": [], "aliases": []},
        )

        size = variant.get("size_ml")
        if size not in (None, ""):
            try:
                value = float(size)
                if value not in target["formats_ml"]:
                    target["formats_ml"].append(value)
            except (TypeError, ValueError):
                pass

        for source_key, target_key in (("gtins", "gtins"), ("mpns", "mpns")):
            values = variant.get(source_key) or []
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                for value in values:
                    value = str(value or "").strip()
                    if value and value not in target[target_key]:
                        target[target_key].append(value)

        aliases = variant.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if isinstance(aliases, list):
            for alias in aliases:
                alias = str(alias or "").strip()
                if alias and alias not in target["aliases"]:
                    target["aliases"].append(alias)

    catalog: List[Dict[str, Any]] = []

    for product in products:
        if not isinstance(product, dict):
            continue

        product_id = str(product.get("product_id") or "").strip()
        brand = str(product.get("brand_name") or "").strip()
        name = str(product.get("canonical_name") or "").strip()

        if not product_id or not name:
            continue

        data = by_product_id.get(
            product_id,
            {"formats_ml": [], "gtins": [], "mpns": [], "aliases": []},
        )

        aliases = list(product.get("aliases") or []) if isinstance(product.get("aliases"), list) else []
        aliases.extend(data["aliases"])
        aliases = list(dict.fromkeys(str(x).strip() for x in aliases if str(x).strip()))

        catalog.append({
            "id": product_id,
            "brand": brand,
            "name": name,
            "canonical_name": name,
            "catalog_variant": name,
            "aliases": aliases,
            "concentration": str(product.get("concentration") or "").strip(),
            "gender": str(product.get("gender") or "").strip(),
            "family_id": str(product.get("family_id") or "").strip(),
            "family_name": str(product.get("family_name") or "").strip(),
            "formats_ml": data["formats_ml"],
            "gtins": data["gtins"],
            "mpns": data["mpns"],
        })

    return catalog


_PRODUCT_MATCHER_CATALOG = _load_product_matcher_catalog()
_PRODUCT_MATCHER = ProductMatcher(_PRODUCT_MATCHER_CATALOG)

FRONTEND_INDEX = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "index.html"
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

GLOBAL_SEARCH_TIMEOUT = 90


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

    # Retailers such as Deloox sometimes expose the format only in the
    # product URL or raw payload while leaving size_ml empty. Include those
    # sources in the central parser so format identity is not lost.
    url = product.get("url") or ""
    if url:
        text += " " + str(url)

    raw_data = product.get("raw_data")
    if isinstance(raw_data, dict):
        for key in ("name", "title", "product_title", "url", "handle"):
            value = raw_data.get(key)
            if value not in (None, ""):
                text += " " + str(value)

    match = re.search(
        r"\b(\d{1,4}(?:[.,]\d+)?)\s*[-_/]?\s*(ml|cl)\b",
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
        ("parfum intense", r"\bparfum intense\b"),
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
# FAMILY REGISTRY / CATALOGO AUTORITATIVO
# ============================================================

FAMILY_REGISTRY_PATH = os.path.join(
    BASE_DIR,
    "family_registry.json",
)


def catalog_norm(value: Any) -> str:
    """Normalize catalog text deterministically, without fuzzy matching."""
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char
        for char in text
        if not unicodedata.combining(char)
    )
    # ASCII and typographic apostrophes are explicit equivalents.
    text = text.replace("’", "").replace("'", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _catalog_clean_text(value: Any) -> str:
    """
    Rimuove soltanto elementi commerciali non identitari.

    Non rimuove termini di genere: "for him", "for her", "men",
    "women", "homme", "femme", "voor", ecc. restano significativi.
    """
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
        r"extrait\s+de\s+parfum|parfum\s+intense|"
        r"edp|edt|edc|parfum|perfume|"
        r"spray)\b",
        " ",
        text,
        flags=re.I,
    )

    return re.sub(r"\s+", " ", text).strip()


def catalog_variant_key(value: Any) -> str:
    return _catalog_clean_text(value)


def _catalog_candidate_variant_key(product: Dict[str, Any]) -> str:
    """
    Restituisce la chiave identitaria della variante commerciale.

    La chiave elimina soltanto informazioni non appartenenti alla variante:
    formato, concentrazione e marcatori espliciti di genere. Il confronto
    con il Family Registry viene poi fatto per uguaglianza, mai per
    sottostringa: una variante autorizzata "Hawas" non può quindi validare
    automaticamente "Hawas Al Wisam".
    """
    raw_name = (
        product.get("canonical_name")
        or product.get("name")
        or product.get("title")
        or product.get("product_name")
        or ""
    )

    key = catalog_variant_key(raw_name)

    key = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|l|g|kg|oz)\b",
        " ",
        key,
    )
    key = re.sub(
        r"\b(?:eau de parfum|eau de toilette|eau de cologne|"
        r"eau fraiche|extrait de parfum|parfum intense|parfum|perfume|edp|edt|edc|spray)\b",
        " ",
        key,
    )

    # Genere = attributo separato, mai parte della variante visualizzata.
    # Sono comprese le principali formulazioni commerciali multilingua.
    key = re.sub(
        r"\b(?:for\s+(?:him|her|men|women)|"
        r"pour\s+(?:homme|femme|hommes|femmes)|"
        r"voor\s+(?:mannen|dames|vrouwen)|"
        r"men|women|man|woman|male|female|"
        r"homme|femme|heren|mannen|dames|vrouwen|uomo|donna|unisex)\b",
        " ",
        key,
        flags=re.I,
    )

    # Sample is a FORMAT/offer-type marker, not part of the perfume variant
    # identity. A sample titled "Hawas Ice sample 10 ml" must therefore map
    # to the same commercial variant "Hawas Ice" when the user explicitly
    # requests the small format.
    key = re.sub(
        r"\b(?:sample|samples|campione|campioncino|echantillon|muestra)\b",
        " ",
        key,
        flags=re.I,
    )

    return re.sub(r"\s+", " ", key).strip()


def _catalog_tokens(value: Any) -> List[str]:
    return _catalog_clean_text(value).split()


def _catalog_phrase_equal(left: Any, right: Any) -> bool:
    return _catalog_clean_text(left) == _catalog_clean_text(right)


def _catalog_phrase_in_text(phrase: Any, text: Any) -> bool:
    phrase_clean = _catalog_clean_text(phrase)
    text_clean = _catalog_clean_text(text)

    if not phrase_clean or not text_clean:
        return False

    return (
        f" {phrase_clean} " in f" {text_clean} "
    )


def _catalog_gender_class(value: Any) -> str:
    """
    Restituisce la classe di genere esplicita.

    Una variante senza genere non può essere aliasata automaticamente
    a una variante che introduce "for him/for her", "men/women", ecc.
    """
    tokens = set(_catalog_tokens(value))

    male = {
        "for", "him", "men", "man",
        "homme", "heren", "mannen", "male", "uomo",
    }
    female = {
        "for", "her", "women", "woman",
        "femme", "dames", "vrouwen", "female", "donna",
    }

    # "for" da solo non è una classe: serve la parola successiva.
    male_hit = bool(tokens & {
        "him", "men", "man", "homme", "heren", "mannen", "male", "uomo",
    })
    female_hit = bool(tokens & {
        "her", "women", "woman", "femme", "dames", "vrouwen", "female", "donna",
    })

    if male_hit and not female_hit:
        return "male"
    if female_hit and not male_hit:
        return "female"
    if male_hit and female_hit:
        return "mixed"

    return "none"


def _load_family_registry() -> List[Dict[str, Any]]:
    """
    Carica il catalogo esterno senza inserire conoscenza specifica nel main.

    Sono supportati sia il formato "allowed_variants" sia il formato
    "products", così il registro resta un semplice file dati.
    """
    try:
        with open(
            FAMILY_REGISTRY_PATH,
            "r",
            encoding="utf-8",
        ) as file:
            payload = json.load(file)
    except Exception as exc:
        print(
            "FAMILY_REGISTRY_LOAD_ERROR:",
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return []

    families = payload.get("families") if isinstance(payload, dict) else None
    if not isinstance(families, list):
        return []

    output: List[Dict[str, Any]] = []

    for family in families:
        if not isinstance(family, dict):
            continue

        variants = (
            family.get("allowed_variants")
            or family.get("products")
            or []
        )

        if not isinstance(variants, list):
            variants = []

        normalized_variants = []

        for variant in variants:
            if not isinstance(variant, dict):
                continue

            canonical_name = str(
                variant.get("canonical_name")
                or variant.get("name")
                or ""
            ).strip()

            # The registry stores the brand at family level.  Some historical
            # registry versions also repeated that brand inside
            # canonical_name (for example "Brand Variant").  Canonical
            # identity must keep the brand in its own field, so remove only
            # a leading family-brand prefix from the canonical variant name.
            # Do not remove gender/variant words: they remain part of the
            # commercial variant identity.
            family_brand = str(family.get("brand") or "").strip()
            if family_brand and canonical_name:
                canonical_name = re.sub(
                    rf"^\s*{re.escape(family_brand)}(?:\s*[-:–—]\s*|\s+)",
                    "",
                    canonical_name,
                    flags=re.I,
                ).strip()

            if not canonical_name:
                continue

            aliases = variant.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            if not isinstance(aliases, list):
                aliases = []

            # Il canonical è sempre una forma valida di riferimento.
            valid_aliases = [canonical_name]

            for alias in aliases:
                alias = str(alias or "").strip()
                if not alias:
                    continue

                # Gli alias dichiarati dal Registry sono equivalenze
                # esplicite e autorevoli: non vanno filtrati dal main.
                valid_aliases.append(alias)

            valid_aliases = list(dict.fromkeys(valid_aliases))
            normalized_variants.append(
                {
                    "canonical_name": canonical_name,
                    "aliases": valid_aliases,
                    "normalized_aliases": tuple(
                        catalog_variant_key(alias)
                        for alias in valid_aliases
                        if catalog_variant_key(alias)
                    ),
                }
            )

        if not normalized_variants:
            continue

        query_aliases = (
            family.get("query_aliases")
            or family.get("search_aliases")
            or family.get("search_name")
            or family.get("canonical_family_name")
            or []
        )

        if isinstance(query_aliases, str):
            query_aliases = [query_aliases]

        if not isinstance(query_aliases, list):
            query_aliases = []

        output.append(
            {
                "family_id": str(
                    family.get("family_id") or ""
                ).strip(),
                "brand": str(
                    family.get("brand") or ""
                ).strip(),
                "query_aliases": [
                    str(value).strip()
                    for value in query_aliases
                    if str(value or "").strip()
                ],
                "variants": normalized_variants,
                "normalized_query_aliases": tuple(
                    catalog_variant_key(value)
                    for value in query_aliases
                    if catalog_variant_key(value)
                ),
            }
        )

    return output


FAMILY_REGISTRY = _load_family_registry()


def _build_family_registry_index(
    families: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Build the normalized family-query index once at startup."""
    index: Dict[str, Dict[str, Any]] = {}
    for family in families:
        for alias_key in family.get("normalized_query_aliases", ()):
            if alias_key:
                index.setdefault(alias_key, family)
    return index


FAMILY_REGISTRY_INDEX = _build_family_registry_index(FAMILY_REGISTRY)


def _catalog_detected_brand(product: Dict[str, Any]) -> str:
    """Recover an explicitly published retailer brand from known catalog brands.

    Some adapters leave ``brand`` empty even though the retailer title is
    formatted as ``Brand - Product``.  For catalog-controlled searches that
    must not be treated as an unknown brand: a known catalog brand explicitly
    present in the title is authoritative evidence.
    """
    direct = product_field(
        product,
        "brand",
        "manufacturer",
        "maker",
        "source_brand",
    )
    source = product.get("source")
    if isinstance(source, dict) and not direct:
        direct = str(
            source.get("brand")
            or source.get("manufacturer")
            or source.get("maker")
            or source.get("source_brand")
            or ""
        ).strip()

    if direct:
        return catalog_norm(direct)

    text = catalog_norm(_catalog_product_text(product))
    if not text:
        return ""

    known: Dict[str, str] = {}
    for family in FAMILY_REGISTRY:
        brand = str(family.get("brand") or "").strip()
        if brand:
            known[catalog_norm(brand)] = brand

    # The product catalog is also a source of known brands.  Longest first
    # prevents a short brand token from stealing a multi-word brand.
    for item in _PRODUCT_MATCHER_CATALOG:
        if not isinstance(item, dict):
            continue
        brand = str(
            item.get("brand")
            or item.get("manufacturer")
            or item.get("maker")
            or ""
        ).strip()
        if brand:
            known[catalog_norm(brand)] = brand

    for brand_norm, brand_display in sorted(
        known.items(),
        key=lambda pair: len(pair[0]),
        reverse=True,
    ):
        if not brand_norm:
            continue
        if re.search(rf"\b{re.escape(brand_norm)}\b", text, flags=re.I):
            return brand_norm

    return ""


def _catalog_brand_matches(
    product: Dict[str, Any],
    family: Dict[str, Any],
) -> bool:
    expected_brand = catalog_norm(
        family.get("brand")
    )

    if not expected_brand:
        return True

    actual_brand = _catalog_detected_brand(product)

    # Missing brand is acceptable only when the retailer genuinely did not
    # publish one.  If a known brand is explicitly present in the candidate
    # title/source, it becomes a hard constraint.
    if not actual_brand:
        return True

    return actual_brand == expected_brand


def _catalog_product_text(product: Dict[str, Any]) -> str:
    values = [
        product_field(
            product,
            "name",
            "title",
            "product_name",
        ),
    ]

    source = product.get("source")
    if isinstance(source, dict):
        values.extend(
            [
                source.get("name"),
                source.get("title"),
            ]
        )

    return " ".join(
        str(value or "")
        for value in values
    ).strip()


def _catalog_gender_neutral_key(value: Any) -> str:
    """
    Restituisce la forma identitaria senza marcatori di genere espliciti.

    La rimozione è usata solo come seconda possibilità di confronto:
    il genere dichiarato dal candidato resta sempre una informazione
    vincolante quando il catalogo contiene varianti con lo stesso nucleo.
    """
    text = _catalog_clean_text(value)

    text = re.sub(
        r"\b(?:for\s+(?:him|her|men|women)|"
        r"pour\s+(?:homme|femme|hommes|femmes)|"
        r"voor\s+(?:mannen|dames|vrouwen)|"
        r"(?:men|women|mannen|dames|vrouwen|"
        r"homme|femme|uomo|donna|male|female))\b",
        " ",
        text,
        flags=re.I,
    )

    return re.sub(r"\s+", " ", text).strip()


def _catalog_variant_for_product(
    product: Dict[str, Any],
    family: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Identifica una sola variante autorizzata del catalogo.

    Il confronto è deterministico: la chiave della variante candidata deve
    essere identica alla chiave di una forma autorizzata. Non viene usata
    alcuna inclusione per sottostringa, perché trasformerebbe una famiglia
    ampia in un contenitore di falsi positivi.

    Il genere viene valutato separatamente. Questo permette, ad esempio,
    di trattare "Hawas For Him" come la variante "Hawas" + Uomo nel titolo,
    senza confondere "Hawas" con "Hawas For Her".
    """
    if not _catalog_brand_matches(product, family):
        return None

    candidate_text = _catalog_clean_text(_catalog_product_text(product))
    if not candidate_text:
        return None

    brand = _catalog_clean_text(family.get("brand"))
    if brand:
        candidate_text = re.sub(
            rf"\b{re.escape(brand)}\b",
            " ",
            candidate_text,
            flags=re.I,
        )
        candidate_text = re.sub(r"\s+", " ", candidate_text).strip()

    candidate_key = _catalog_candidate_variant_key(product)
    if brand:
        candidate_key = re.sub(
            rf"\b{re.escape(brand)}\b",
            " ",
            candidate_key,
            flags=re.I,
        )
        candidate_key = re.sub(r"\s+", " ", candidate_key).strip()
    if not candidate_key:
        return None

    candidate_gender = _catalog_gender_class(candidate_text)
    matches: List[Tuple[int, Dict[str, Any]]] = []

    for variant in family.get("variants", []):
        canonical = str(variant.get("canonical_name") or "").strip()
        aliases = variant.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]

        variant_forms = [canonical]
        variant_forms.extend(str(alias or "").strip() for alias in aliases)

        # Tutte le forme della stessa variante devono ridursi alla stessa
        # chiave identitaria. La specificità serve solo a scegliere fra alias
        # equivalenti, mai fra varianti diverse.
        canonical_key = _catalog_gender_neutral_key(canonical)
        alias_keys = {
            _catalog_gender_neutral_key(alias)
            for alias in aliases
            if _catalog_gender_neutral_key(alias)
        }
        variant_keys = {key for key in (canonical_key, *alias_keys) if key}

        if candidate_key not in variant_keys:
            continue

        # Only the canonical variant name defines the catalog gender.
        variant_gender = _catalog_gender_class(canonical)

        # Se il candidato espone un genere esplicito, deve essere compatibile
        # con quello canonico. Un candidato senza genere può invece usare un
        # alias AUTOREVOLE del Registry che rappresenta una forma commerciale
        # abbreviata di una variante gendered: l'alias è già la prova esplicita
        # che quella forma appartiene a quella variante. Non facciamo questa
        # inferenza sul solo testo del prodotto.
        if variant_gender != "none":
            alias_match = candidate_key in alias_keys and candidate_key != canonical_key
            if candidate_gender != variant_gender and not (candidate_gender == "none" and alias_match):
                continue
        elif candidate_gender == "mixed":
            continue

        specificity = max(
            len(_catalog_gender_neutral_key(form))
            for form in variant_forms
            if _catalog_gender_neutral_key(form)
        )
        matches.append((specificity, variant))

    if not matches:
        return None

    matches.sort(key=lambda item: item[0], reverse=True)
    best_specificity = matches[0][0]
    best = [variant for specificity, variant in matches if specificity == best_specificity]

    canonical_names = {str(item.get("canonical_name") or "") for item in best}
    if len(canonical_names) != 1:
        return None

    return best[0]


def _catalog_family_for_query(
    query: str,
) -> Optional[Dict[str, Any]]:
    query_clean = catalog_variant_key(query)

    if not query_clean:
        return None

    family = FAMILY_REGISTRY_INDEX.get(query_clean)
    if family is not None:
        return family

    # If a cataloged family is present in a longer query, keep the query
    # under catalog control. An unauthorized appended variant is therefore
    # rejected instead of falling back to generic matching.
    padded_query = f" {query_clean} "
    for alias_key, candidate_family in FAMILY_REGISTRY_INDEX.items():
        if f" {alias_key} " in padded_query:
            return candidate_family

    return None


def _catalog_requested_variant(
    query: str,
    family: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Resolve a specific family variant from an explicit query.

    The query uses the same neutral identity rules as a retailer title:
    brand, format/concentration and gender wording are removed for the
    variant key, while the explicit gender remains available to disambiguate
    gendered variants.
    """
    query_clean = _catalog_clean_text(query)

    # "sample/campione" is a format request, not part of the commercial
    # variant identity. Remove it before resolving the catalog variant.
    query_clean = re.sub(
        r"\b(?:sample|samples|campione|campioncino|echantillon|muestra)\b",
        " ",
        query_clean,
        flags=re.I,
    )
    query_clean = re.sub(r"\s+", " ", query_clean).strip()

    brand = _catalog_clean_text(family.get("brand"))
    if brand:
        query_clean = re.sub(
            rf"\b{re.escape(brand)}\b",
            " ",
            query_clean,
            flags=re.I,
        )
        query_clean = re.sub(r"\s+", " ", query_clean).strip()

    query_key = _catalog_candidate_variant_key({"name": query_clean})
    query_gender = _catalog_gender_class(query_clean)
    if not query_key:
        return None

    matches: List[Dict[str, Any]] = []

    for variant in family.get("variants", []):
        forms = [
            str(variant.get("canonical_name") or ""),
            *[
                str(alias or "")
                for alias in (variant.get("aliases") or [])
            ],
        ]
        neutral_keys = {
            _catalog_gender_neutral_key(form)
            for form in forms
            if _catalog_gender_neutral_key(form)
        }
        if query_key not in neutral_keys:
            continue

        variant_gender = _catalog_gender_class(str(variant.get("canonical_name") or ""))
        # When the user explicitly requests a gendered variant, a neutral
        # variant is not an acceptable substitute. This is what keeps
        # "9 PM Pour Femme" distinct from plain "9 PM".
        if query_gender != "none":
            if variant_gender != query_gender:
                continue
        elif variant_gender == "mixed":
            continue

        matches.append(variant)

    if len(matches) == 1:
        return matches[0]

    # A completely neutral query can legitimately identify one neutral
    # variant. It must never be used to guess between two gendered variants.
    neutral = [
        variant
        for variant in matches
        if _catalog_gender_class(
            " ".join(
                [str(variant.get("canonical_name") or "")]
                + [str(x or "") for x in (variant.get("aliases") or [])]
            )
        ) == "none"
    ]
    if len(neutral) == 1:
        return neutral[0]

    return None


def _catalog_match(
    product: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    """
    Risolve il candidato esclusivamente contro la famiglia individuata dalla
    query.

    Regole:
    - una query che identifica una famiglia autorizza tutte e sole le sue
      varianti presenti nel Registry;
    - una query che identifica una variante autorizza soltanto quella
      variante;
    - il confronto della variante è per uguaglianza della chiave identitaria,
      mai per sottostringa;
    - il genere serve solo a distinguere varianti omonime/genderizzate;
    - il brand del Registry viene propagato anche quando il retailer non lo
      espone.
    """
    family = _catalog_family_for_query(query)
    if family is None:
        return None

    query_key = catalog_variant_key(query)
    is_family_query = query_key in family.get("normalized_query_aliases", ())

    requested = None if is_family_query else _catalog_requested_variant(
        query,
        family,
    )

    # Una query che contiene il nome della famiglia ma aggiunge una variante
    # non registrata non deve ricadere nel matching generico.
    if not is_family_query and requested is None:
        return None

    variant = _catalog_variant_for_product(product, family)
    if variant is None:
        return None

    if requested is not None and variant is not requested:
        return None

    result = dict(product)
    canonical_name = str(variant.get("canonical_name") or "").strip()
    family_brand = str(family.get("brand") or "").strip()

    if not canonical_name:
        return None

    result["name"] = canonical_name
    result["canonical_name"] = canonical_name

    if family_brand:
        result["canonical_brand"] = family_brand
        result["brand"] = family_brand

    result["family_id"] = family.get("family_id", "")
    result["family_name"] = (
        family.get("query_aliases", [""])[0]
        if family.get("query_aliases")
        else ""
    )
    result["catalog_variant"] = canonical_name

    candidate_gender = _catalog_gender_class(_catalog_product_text(product))
    if candidate_gender == "male":
        result["gender"] = "Uomo"
    elif candidate_gender == "female":
        result["gender"] = "Donna"

    result["match_method"] = "family_registry_alias"
    return result


# ============================================================
# VALIDAZIONE
# ============================================================

def _query_requests_sample(query: str) -> bool:
    """Return True only when the user explicitly asks for a sample."""
    query_normalized = norm(query)
    tokens = set(query_normalized.split())
    markers = {
        "sample",
        "samples",
        "campione",
        "campioncino",
        "échantillon",
        "echantillon",
        "muestra",
    }
    return bool(tokens & {norm(value) for value in markers})


def _non_single_product_match(product: Dict[str, Any]) -> Optional[str]:
    """
    Identify products that ScentHunter must never return.

    The decision is based on the product identity text, not on the user's
    query. Therefore typing "Hawas set" can never turn a set into a valid
    perfume offer.
    """
    values: List[str] = []

    for key in (
        "name",
        "title",
        "product_name",
        "product_line",
        "variant",
        "format",
        "packaging_type",
        "product_type",
        "category",
        "product_category",
    ):
        value = product.get(key)
        if value not in (None, ""):
            values.append(str(nested_value(value)))

    source = product.get("source")
    if isinstance(source, dict):
        for key in (
            "source_name",
            "name",
            "title",
            "url",
        ):
            value = source.get(key)
            if value not in (None, ""):
                values.append(str(value))

    url = product.get("url")
    if url:
        values.append(str(url))

    text = norm(" ".join(values))
    if not text:
        return None

    # These categories are ALWAYS forbidden, even if the user explicitly
    # types the forbidden word. ScentHunter compares single perfumes only.
    always_blocked = {
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
        "sample",
        "samples",
        "sample service",
        "campione",
        "campioncino",
        "échantillon",
        "echantillon",
        "muestra",
        "tester",
        "testeur",
        "shampoo",
        "shower gel",
        "shower cream",
        "body wash",
        "body lotion",
        "body cream",
        "body milk",
        "body butter",
        "body spray",
        "deodorant",
        "deo spray",
        "aftershave",
        "after shave",
        "hair mist",
        "makeup",
        "cosmetics",
        "cosmetic",
        "skincare",
        "skin care",
        "cosmetici",
        "creme corpo",
        "crema corpo",
        "gel doccia",
        "bagnoschiuma",
        "deodorante",
        "coffret",
        "astuccio",
        "pochette",
    }

    for phrase in always_blocked:
        phrase_normalized = norm(phrase)
        if phrase_normalized and (
            f" {phrase_normalized} " in f" {text} "
        ):
            return phrase_normalized

    return None


def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Central product validation.

    ScentHunter returns ONLY single perfume references:
    - no cosmetics/body products;
    - no sets, coffrets, bundles, boxes or testers;
    - samples, sample services, campioncini and testers are always rejected;
    - explicit small-size queries are exact, but they do not turn a sample
      listing into a valid perfume offer.
    """
    query_normalized = norm(query)

    if not query_normalized:
        return False

    name = product_field(
        product,
        "name",
        "title",
        "product_name",
    )

    source = product.get("source")

    if isinstance(source, dict) and not name:
        name = str(
            source.get("name")
            or source.get("title")
            or ""
        ).strip()

    name_normalized = norm(name)

    if not name_normalized:
        return False

    # --------------------------------------------------------
    # HARD PRODUCT-TYPE FILTER
    # --------------------------------------------------------
    # This filter is intentionally independent from the query. A user cannot
    # make a set/body product valid by typing "set", "deodorant", etc.
    if _non_single_product_match(product) is not None:
        return False

    query_size_match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*[-_/]?\s*(ml|cl)\b",
        query_normalized,
        re.I,
    )
    query_size_ml: Optional[float] = None
    if query_size_match:
        query_size_ml = float(
            query_size_match.group(1).replace(",", ".")
        )
        if query_size_match.group(2).lower() == "cl":
            query_size_ml *= 10

    query_requests_sample = _query_requests_sample(query)
    query_requests_small_format = (
        query_requests_sample
        or (
            query_size_ml is not None
            and query_size_ml <= 10
        )
    )

    product_size = product_size_ml(product)

    # Base search: no mini/sample <=10 ml.
    # Explicit small-size/sample search: small format is allowed.
    if product_size is not None and product_size <= 10:
        if not query_requests_small_format:
            return False

    # Explicit format request is exact. Never return a 5 ml product for a
    # 10 ml query, nor a 100 ml bottle for a 10 ml query.
    if query_size_ml is not None and product_size is not None:
        if abs(product_size - query_size_ml) > 0.01:
            return False

    # Samples/testers are already rejected by the hard product-type filter.

    # --------------------------------------------------------
    # CATALOGO AUTORITATIVO
    # --------------------------------------------------------
    catalog_family = _catalog_family_for_query(query)

    if catalog_family is not None:
        return _catalog_match(
            product,
            query,
        ) is not None

    # --------------------------------------------------------
    # MATCHING GENERICO PER FAMIGLIE NON CATALOGATE
    # --------------------------------------------------------
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
        and token not in {"sample", "samples", "campione", "campioncino"}
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
        "for",
        "men",
        "women",
        "homme",
        "femme",
        "unisex",
    }

    # A requested size is an attribute, not part of the product identity.
    query_tokens = [
        token
        for token in query_tokens
        if token not in {"ml", "cl"}
    ]

    family_tokens = [
        token
        for token in query_tokens
        if token not in generic_tokens
        and not token.replace(".", "", 1).isdigit()
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

def product_identity_key(product: Dict[str, Any]) -> tuple:
    store = norm(product.get("store", ""))

    variant_id = identity_value(
        product,
        "store_variant_id",
        "variant_id",
    )
    product_id = identity_value(
        product,
        "store_product_id",
        "product_id",
        "catalog_id",
    )
    gtin = identity_value(
        product,
        "gtin",
        "ean",
        "ean13",
        "barcode",
        "upc",
    )
    sku = identity_value(
        product,
        "sku",
    )

    if variant_id:
        return ("variant", store, norm(variant_id))

    if product_id:
        return ("product", store, norm(product_id), norm(product.get("name", "")))

    if gtin:
        return ("gtin", store, norm(gtin))

    if sku:
        return ("sku", store, norm(sku))

    name = norm(
        product_field(
            product,
            "name",
            "title",
            "product_name",
        )
    )

    source = product.get("source")
    if isinstance(source, dict):
        if not name:
            name = norm(source.get("source_name", ""))

    size = product_size_ml(product)
    concentration = product_concentration(product)

    return (
        "fallback",
        store,
        name,
        size,
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


def _display_brand(product: Dict[str, Any]) -> str:
    # Canonical identity wins over retailer/raw fields.  This is especially
    # important when a retailer title contains only the variant name and the
    # Family Registry supplies the authoritative brand.
    return (
        product_field(
            product,
            "canonical_brand",
            "brand",
            "source_brand",
        )
        or ""
    ).strip()


def _display_raw_name(product: Dict[str, Any]) -> str:
    return (
        product.get("canonical_name")
        or product_field(
            product,
            "name",
            "title",
            "product_name",
        )
        or ""
    ).strip()


def _display_gender(product: Dict[str, Any], raw_name: str) -> str:
    explicit = product_field(
        product,
        "gender",
        "genere",
        "sex",
    )

    source = product.get("source")
    if isinstance(source, dict) and not explicit:
        explicit = str(
            source.get("gender")
            or source.get("genere")
            or source.get("sex")
            or ""
        ).strip()

    gender = _catalog_gender_class(
        " ".join(
            value
            for value in (explicit, raw_name)
            if value
        )
    )

    if gender == "male":
        return "Uomo"
    if gender == "female":
        return "Donna"

    return ""


def _display_variant_name(
    product: Dict[str, Any],
    brand: str,
    raw_name: str,
) -> str:
    """
    Costruisce esclusivamente il nome della variante.

    Formato, concentrazione e genere sono attributi separati e non devono
    entrare nella variante visualizzata. Il genere viene poi aggiunto dal
    formatter come "Uomo" o "Donna".
    """
    variant = str(raw_name or "").strip()

    if brand:
        # Rimuove eventuali prefissi di brand ripetuti ("Brand - Brand -
        # Variante") senza toccare occorrenze del brand che appartengono
        # realmente al nome commerciale.
        brand_pattern = re.compile(
            rf"^\s*{re.escape(str(brand).strip())}\s*(?:[-:–—]\s*)?",
            flags=re.I,
        )
        while True:
            cleaned = brand_pattern.sub("", variant, count=1)
            if cleaned == variant:
                break
            variant = cleaned

    variant = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|l|g|kg|oz)\b",
        " ",
        variant,
        flags=re.I,
    )

    variant = re.sub(
        r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|"
        r"eau\s+de\s+cologne|eau\s+fraiche|"
        r"extrait\s+de\s+parfum|eau\s+de\s+parfum\s+spray|"
        r"parfum\s+intense|edp|edt|edc|parfum|perfume|spray)\b",
        " ",
        variant,
        flags=re.I,
    )

    # Se il nome è già canonico/catalogato, le parole di genere possono
    # essere parte integrante della variante (es. "For Him", "Pour Femme").
    # Non vanno distrutte: altrimenti due referenze diverse diventano la
    # stessa variante. Per i nomi RAW, invece, il genere resta un attributo
    # separato e può essere ripulito dal titolo.
    is_canonical_variant = bool(
        product.get("catalog_variant")
        or product.get("canonical_name")
    )

    if not is_canonical_variant:
        variant = re.sub(
            r"\b(?:for\s+(?:him|her|men|women)|"
            r"pour\s+(?:homme|femme|hommes|femmes)|"
            r"voor\s+(?:mannen|dames|vrouwen)|"
            r"men|women|man|woman|male|female|homme|femme|heren|mannen|"
            r"dames|vrouwen|uomo|donna|unisex)\b",
            " ",
            variant,
            flags=re.I,
        )

    # Elimina parentesi vuote e punteggiatura residua generata dalla pulizia.
    variant = re.sub(r"\(\s*\)", " ", variant)
    variant = re.sub(r"\s+", " ", variant).strip(" -–—:|/")
    return re.sub(r"\s+", " ", variant).strip()


def _format_result_title(product: Dict[str, Any]) -> str:
    """
    Costruisce il titolo visualizzato in modo uniforme per qualunque
    profumo:

        Brand-Variante [Concentrazione] [Uomo/Donna]

    La variante viene presa dall'identità canonica quando disponibile;
    in caso contrario viene ricavata dal nome del candidato. Nessuna
    regola dipende da un marchio o profumo specifico.
    """
    brand = _display_brand(product)
    raw_name = _display_raw_name(product)

    variant = _display_variant_name(
        product,
        brand,
        raw_name,
    )

    if not variant:
        variant = raw_name or "Profumo"

    concentration = product_concentration(product)
    concentration_display = {
        "eau de parfum": "Eau de Parfum",
        "eau de toilette": "Eau de Toilette",
        "eau de cologne": "Eau de Cologne",
        "extrait de parfum": "Extrait de Parfum",
        "parfum intense": "Parfum Intense",
        "parfum": "Parfum",
    }.get(
        concentration,
        concentration.title() if concentration else "",
    )

    gender = _display_gender(
        product,
        raw_name,
    )

    # If the gender is already embedded in the canonical commercial variant,
    # do not append a second "Uomo/Donna" token.  The variant remains intact.
    if re.search(
        r"\b(?:for\s+him|for\s+her|pour\s+homme|pour\s+femme|"
        r"men|women|man|woman|male|female|homme|femme|heren|mannen|dames|"
        r"vrouwen|uomo|donna|unisex)\b",
        catalog_norm(variant),
        re.I,
    ):
        gender = ""

    parts = []
    if brand:
        parts.append(f"{brand}-{variant}")
    else:
        parts.append(variant)

    if concentration_display:
        parts.append(concentration_display)
    if gender:
        parts.append(gender)

    return " ".join(parts).strip()


def _result_group_key(product: Dict[str, Any]) -> tuple:
    """
    Raggruppa le offerte che rappresentano la stessa referenza.

    Per le famiglie catalogate la chiave è la variante canonica. Per le
    altre famiglie usa brand + nome commerciale ripulito da formato e
    concentrazione, mantenendo le differenze reali della variante.
    """
    brand = catalog_norm(_display_brand(product))

    catalog_variant = catalog_norm(
        product.get("catalog_variant")
        or product.get("canonical_name")
        or ""
    )

    if catalog_variant:
        return ("catalog", brand, catalog_variant)

    raw_name = _display_raw_name(product)
    name_key = catalog_norm(raw_name)

    name_key = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|l|g|kg|oz)\b",
        " ",
        name_key,
        flags=re.I,
    )
    name_key = re.sub(
        r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|"
        r"eau\s+de\s+cologne|eau\s+fraiche|"
        r"extrait\s+de\s+parfum|edp|edt|edc|parfum|perfume|spray)\b",
        " ",
        name_key,
        flags=re.I,
    )

    if brand:
        name_key = re.sub(
            rf"\b{re.escape(brand)}\b",
            " ",
            name_key,
            flags=re.I,
        )

    name_key = re.sub(r"\s+", " ", name_key).strip()

    return ("generic", brand, name_key)


def _collapse_family_results(
    products: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    """
    Raggruppa le offerte per variante canonica senza perdere gli store.

    Il vecchio comportamento conservava una sola offerta (la più economica)
    per variante. Durante una ricerca progressiva questo era distruttivo:
    quando arrivava un altro negozio, l'offerta precedente poteva sparire
    dal risultato. Ora ogni variante conserva tutte le offerte realmente
    trovate; il campo principale rappresenta comunque l'offerta migliore per
    mantenere compatibilità con il formato precedente.
    """
    family = _catalog_family_for_query(query)

    if family is None:
        return products

    grouped: Dict[tuple, List[Dict[str, Any]]] = {}

    for product in products:
        key = _result_group_key(product)
        grouped.setdefault(key, []).append(dict(product))

    ordered: List[Dict[str, Any]] = []
    family_brand_key = catalog_norm(family.get("brand"))

    for variant in family.get("variants", []):
        canonical_key = catalog_norm(variant.get("canonical_name"))
        matching_offers: List[Dict[str, Any]] = []

        for key, offer_list in grouped.items():
            if (
                key[0] == "catalog"
                and key[1] == family_brand_key
                and key[2] == canonical_key
            ):
                matching_offers.extend(offer_list)

        if not matching_offers:
            continue

        # Deduplica a livello di singola offerta, mantenendo URL/store/
        # formato distinti. Questo è importante perché più varianti Shopify
        # dello stesso prodotto possono arrivare dallo stesso scraper.
        unique_offers: List[Dict[str, Any]] = []
        seen_offer_keys = set()

        for offer in matching_offers:
            offer_key = (
                norm(offer.get("store", "")),
                str(offer.get("url", "") or "").strip().lower(),
                str(offer.get("size_ml", "") or "").strip(),
                str(offer.get("price", "") or "").strip(),
            )
            if offer_key in seen_offer_keys:
                continue
            seen_offer_keys.add(offer_key)
            unique_offers.append(offer)

        def _offer_sort_key(offer: Dict[str, Any]) -> tuple:
            availability = product_availability(offer)
            availability_rank = {
                "in stock": 0,
                "in_stock": 0,
                "available": 0,
                "out of stock": 2,
                "out_of_stock": 2,
                "unknown": 1,
            }.get(availability, 1)
            price = price_num(offer.get("price"))
            if price is None:
                price = float("inf")
            return (
                availability_rank,
                price,
                norm(offer.get("store", "")),
                str(offer.get("url", "") or "").strip().lower(),
            )

        unique_offers = sorted(unique_offers, key=_offer_sort_key)
        if not unique_offers:
            continue

        # L'oggetto rappresentativo resta compatibile con il vecchio schema:
        # nome/prezzo/store indicano l'offerta migliore, mentre "offers"
        # contiene l'intero confronto tra i negozi.
        representative = dict(unique_offers[0])
        representative["offers"] = unique_offers
        representative["offer_count"] = len(unique_offers)
        representative["stores"] = list(dict.fromkeys(
            str(item.get("store") or "").strip()
            for item in unique_offers
            if str(item.get("store") or "").strip()
        ))
        ordered.append(representative)

    return ordered


def _repair_mojibake(value: Any) -> Any:
    """Repair common UTF-8-as-Windows-1252 display corruption recursively."""
    if isinstance(value, str):
        if not any(marker in value for marker in ("â", "Ã", "Â", "ð")):
            return value
        try:
            repaired = value.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return value
        return repaired if repaired != value else value
    if isinstance(value, list):
        return [_repair_mojibake(item) for item in value]
    if isinstance(value, dict):
        return {key: _repair_mojibake(item) for key, item in value.items()}
    return value


def _prepare_final_results(
    products: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    results = _collapse_family_results(
        unique_results(products),
        query,
    )

    prepared: List[Dict[str, Any]] = []

    for product in results:
        item = dict(product)
        item["name"] = _format_result_title(item)
        item["title"] = item["name"]
        item = _repair_mojibake(item)
        prepared.append(item)

    return sort_by_price(prepared)


# ============================================================
# SCRAPER
# ============================================================

def load_scraper(store: str):
    return importlib.import_module(
        f"scrapers.{store}.scraper"
    )

def normalize_store_product(
    product: Dict[str, Any],
    store: str,
) -> Dict[str, Any]:
    item = dict(product)
    normalized_store = str(store or item.get("store") or "").strip().lower()

    item["store"] = normalized_store

    if normalized_store != "notino":
        return item

    source = item.get("source")
    if not isinstance(source, dict):
        source = {}

    source.update({
        "store": "notino",
        "sourcestore": "notino",
        "sourcename": "Notino",
    })

    item["source"] = source

    name = str(
        item.get("name")
        or item.get("title")
        or item.get("productname")
        or source.get("name")
        or ""
    ).strip()

    if name:
        item.setdefault("canonicalname", name)
        item.setdefault("catalogvariant", name)
        item.setdefault("name", name)

    if item.get("sizeml") is None:
        if item.get("size") is not None:
            item["sizeml"] = item["size"]
        else:
            item["sizeml"] = productsizeml(item)

    if item.get("size") is None and item.get("sizeml") is not None:
        item["size"] = item["sizeml"]

    concentration = str(
        item.get("concentration")
        or item.get("canonicalconcentration")
        or productconcentration(item)
        or ""
    ).strip()

    if concentration:
        item["concentration"] = concentration
        item.setdefault("canonicalconcentration", concentration)

    if item.get("available") is not None:
        item["availability"] = (
            "in stock" if item["available"] else "out of stock"
        )

    return item


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    """
    Discovery uniforme per qualunque negozio e qualunque query.

    Ogni store riceve una sola piccola sequenza di query generiche costruita
    dal Query Analyzer. Non vengono generate query per ogni variante di una
    famiglia: la discovery raccoglie candidati e la validazione centrale
    decide successivamente quali candidati appartengono davvero al prodotto.

    Questo separa nettamente DISCOVERY da IDENTITY MATCH e impedisce che una
    famiglia con molte varianti trasformi una ricerca in decine di richieste
    aggiuntive per singolo negozio.
    """
    module = load_scraper(store)

    search_fn = getattr(module, "search", None)
    if not callable(search_fn):
        search_fn = getattr(module, "scrape", None)

    if not callable(search_fn):
        raise RuntimeError(
            f"{store}: scraper senza funzione search()/scrape()"
        )

    discovery_query = str(query or "").strip()
    attempts = build_search_attempts(store, discovery_query)

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

            product = normalize_store_product(item, store)
            product = resolveactualpriceproduct(product)




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
    # Anche il pre-ranking deve considerare i numeri identitari: non devono
    # favorire un falso candidato che condivide solo una parola generica.
    query_tokens = [
        token
        for token in norm(query).split()
        if token not in IGNORED_WORDS
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


def validatecandidate(
    product: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    try:
        matched = matchesproduct(product, query)
    except Exception as exc:
        print(
            "[CENTRAL VALIDATION ERROR]",
            {
                "store": product.get("store"),
                "query": query,
                "name": product.get("name"),
                "brand": product.get("brand"),
                "canonicalname": product.get("canonicalname"),
                "catalogvariant": product.get("catalogvariant"),
                "sizeml": product.get("sizeml"),
                "concentration": product.get("concentration"),
                "url": product.get("url"),
                "error": repr(exc),
            },
            flush=True,
        )
        return None

    if not matched:
        print(
            "[CENTRAL VALIDATION REJECT]",
            {
                "store": product.get("store"),
                "query": query,
                "name": product.get("name"),
                "brand": product.get("brand"),
                "canonicalname": product.get("canonicalname"),
                "catalogvariant": product.get("catalogvariant"),
                "sizeml": product.get("sizeml"),
                "concentration": product.get("concentration"),
                "gender": product.get("gender"),
                "url": product.get("url"),
            },
            flush=True,
        )
        return None

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

    return _prepare_final_results(
        validated,
        query,
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
        query = job["query"]
        raw_results = list(job["results"])
        errors = dict(job["errors"])
        completed = bool(job["completed"])
        store_status = dict(job.get("store_status", {}))
        diagnostics = dict(job.get("store_diagnostics", {}))
        phase = job.get("phase", "discovery")

    results = _prepare_final_results(raw_results, query)
    return {
        "job_id": job_id,
        "query": query,
        "count": len(results),
        "results": results,
        "comparisons": [],
        "errors": errors,
        "store_status": store_status,
        "store_diagnostics": diagnostics,
        "phase": phase,
        "completed": completed,
        "status": "completed" if completed else "searching",
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
                job["phase"] = "completed"
                job["elapsed"] = round(time.time() - job.get("started_at", time.time()), 3)


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
            "phase": "discovery",
            "started_at": time.time(),
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


@app.get("/diagnostic-search")
def diagnostic_search(
    q: str,
    stores: Optional[str] = None,
):
    """
    Espone il diagnostico generico come endpoint JSON.

    Il diagnostico reale resta in diagnostic_search.py.
    Questo endpoint lo richiama senza duplicare la logica
    nel main e senza introdurre regole specifiche per prodotti.
    """
    query = str(q or "").strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Parametro q mancante",
        )

    selected_stores = None

    if stores:
        selected_stores = [
            store.strip().lower()
            for store in stores.split(",")
            if store.strip()
        ]

        invalid_stores = [
            store
            for store in selected_stores
            if store not in STORES
        ]

        if invalid_stores:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Store non validi: "
                    + ", ".join(invalid_stores)
                    + ". Disponibili: "
                    + ", ".join(STORES)
                ),
            )

    try:
        diagnostic_module = importlib.import_module(
            "diagnostic_search"
        )

        run_query = getattr(
            diagnostic_module,
            "run_query",
            None,
        )

        if not callable(run_query):
            raise RuntimeError(
                "diagnostic_search.py non espone run_query()"
            )

        return run_query(
            query,
            stores=selected_stores,
        )

    except HTTPException:
        raise

    except Exception as exc:
        traceback.print_exc()

        return {
            "query": query,
            "ok": False,
            "error": (
                f"{type(exc).__name__}: {exc}"
            ),
            "traceback": traceback.format_exc(),
        }


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
        nested_offers = product_data.get("offers")

        if isinstance(nested_offers, list) and nested_offers:
            source_offers = nested_offers
        else:
            source_offers = [product_data]

        for source_offer in source_offers:
            value = price_num(
                source_offer.get("price")
            )

            if value is None:
                continue

            offer = dict(source_offer)
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

@app.get("/debug-notino-result", include_in_schema=False)
def debug_notino_result(q: str):
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    try:
        module = importlib.import_module("scrapers.notino.scraper")
        searchfn = getattr(module, "search", None) or getattr(module, "scrape", None)
        if not callable(searchfn):
            raise RuntimeError("Notino scraper senza funzione search/scrape")

        raw = searchfn(query) or []
        normalized = [normalize_store_product(item, "notino") for item in raw]

        validation = []
        for item in normalized:
            try:
                accepted = bool(matchesproduct(item, query))
                error = None
            except Exception as exc:
                accepted = False
                error = repr(exc)

            validation.append({
                "accepted": accepted,
                "error": error,
                "product": item,
            })

        return {
            "query": query,
            "raw_count": len(raw),
            "normalized_count": len(normalized),
            "validation": validation,
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=repr(exc)) from exc

