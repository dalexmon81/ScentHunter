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
    # Soli elementi commerciali/formali che non identificano la referenza.
    # Termini come for/her/him/men/women/by restano SEMPRE identitari:
    # possono distinguere varianti diverse della stessa famiglia.
    "eau",
    "de",
    "parfum",
    "perfume",
    "edp",
    "edt",
    "extrait",
    "spray",
    "ml",
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
# FAMILY REGISTRY / CATALOGO AUTORITATIVO
# ============================================================

FAMILY_REGISTRY_PATH = os.path.join(
    BASE_DIR,
    "family_registry.json",
)


def catalog_norm(value: Any) -> str:
    """
    Normalizzazione usata ESCLUSIVAMENTE dal catalogo famiglie.

    A differenza di norm(), mantiene i caratteri accentati:
    nel catalogo le forme accentate possono quindi restare distinte.
    L'apostrofo tipografico viene trattato come separatore, così
    le forme con apostrofo restano confrontabili con la forma ASCII equivalente.
    """
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFC", text)
    text = text.replace("’", "").replace("'", "")
    text = re.sub(r"[^0-9a-zà-öø-ÿĀ-ž]+", " ", text)
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
        r"extrait\s+de\s+parfum|"
        r"edp|edt|edc|parfum|perfume|"
        r"spray)\b",
        " ",
        text,
        flags=re.I,
    )

    return re.sub(r"\s+", " ", text).strip()


def _catalog_concentration(value: Any) -> str:
    """Extract an explicit concentration without treating it as generic noise."""
    text = catalog_norm(value)
    for label, pattern in (
        ("extrait de parfum", r"\bextrait\s+de\s+parfum\b"),
        ("eau de parfum", r"\beau\s+de\s+parfum\b|\bedp\b"),
        ("eau de toilette", r"\beau\s+de\s+toilette\b|\bedt\b"),
        ("eau de cologne", r"\beau\s+de\s+cologne\b|\bedc\b"),
        ("parfum", r"\bparfum\b"),
    ):
        if re.search(pattern, text, re.I):
            return label
    return ""


def catalog_variant_key(value: str) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(
        char for char in text
        if not unicodedata.combining(char)
    )

    text = text.replace("’", "'")
    text = re.sub(r"[^a-z0-9']+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _catalog_alias_keys(value: Any) -> List[str]:
    """
    Return exact catalog keys plus safe localized gender equivalents.

    This is deliberately generic: it only expands explicit female/male
    audience markers (for her/for him, femme/homme, dames/hommes, etc.).
    It never turns a bare family name into a gendered variant.
    """
    raw = catalog_variant_key(_catalog_clean_text(value))
    if not raw:
        return []

    keys = [raw]
    replacements = (
        (" for her ", " dames "),
        (" for him ", " hommes "),
        (" for her ", " femme "),
        (" for him ", " homme "),
        (" for her ", " women "),
        (" for him ", " men "),
        (" pour femme ", " dames "),
        (" pour homme ", " hommes "),
        (" pour femme ", " femme "),
        (" pour homme ", " homme "),
        (" women ", " dames "),
        (" woman ", " dame "),
        (" men ", " hommes "),
        (" man ", " homme "),
    )

    padded = f" {raw} "
    for source, target in replacements:
        if source in padded:
            candidate = padded.replace(source, target).strip()
            candidate = re.sub(r"\s+", " ", candidate)
            if candidate and candidate not in keys:
                keys.append(candidate)

    return keys


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
        "homme", "heren", "mannen", "male",
    }
    female = {
        "for", "her", "women", "woman",
        "femme", "dames", "vrouwen", "female",
    }

    # "for" da solo non è una classe: serve la parola successiva.
    male_hit = bool(tokens & {
        "him", "men", "man", "homme", "heren", "mannen", "male",
    })
    female_hit = bool(tokens & {
        "her", "women", "woman", "femme", "dames", "vrouwen", "female",
    })

    if male_hit and not female_hit:
        return "male"
    if female_hit and not male_hit:
        return "female"
    if male_hit and female_hit:
        return "mixed"

    return "none"


def _catalog_alias_is_valid(
    canonical_name: str,
    alias: str,
) -> bool:
    """
    Applica due protezioni generiche al dato del catalogo:

    1) un alias che differisce dal canonical_name solo per gli accenti
       NON viene considerato equivalente;
    2) un alias che aggiunge/cambia il genere rispetto al canonical_name
       NON viene considerato equivalente.

    Le vere equivalenze lessicali restano invece possibili quando sono
    esplicitamente dichiarate dal catalogo.
    """
    canonical_clean = _catalog_clean_text(canonical_name)
    alias_clean = _catalog_clean_text(alias)

    if not canonical_clean or not alias_clean:
        return False

    canonical_folded = norm(canonical_clean)
    alias_folded = norm(alias_clean)

    if (
        canonical_clean != alias_clean
        and canonical_folded == alias_folded
    ):
        return False

    canonical_gender = _catalog_gender_class(canonical_name)
    alias_gender = _catalog_gender_class(alias)

    if canonical_gender != alias_gender:
        return False

    return True


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

            normalized_variants.append(
                {
                    "canonical_name": canonical_name,
                    "aliases": list(dict.fromkeys(valid_aliases)),
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

        excluded_values = []
        for key in ("excluded_products", "excluded_variants", "excluded_aliases"):
            values = family.get(key) or []
            if isinstance(values, str):
                values = [values]
            if isinstance(values, list):
                excluded_values.extend(
                    str(value).strip()
                    for value in values
                    if str(value or "").strip()
                )

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
                "excluded": list(dict.fromkeys(excluded_values)),
            }
        )

    return output


FAMILY_REGISTRY = _load_family_registry()


def _catalog_title_matches_family_variant(
    product: Dict[str, Any],
    family: Dict[str, Any],
) -> bool:
    """
    Check whether the retailer title is an exact authorized family variant.

    This is used only as brand-recovery evidence: an unrecognized retailer
    brand must not prevent a deterministic catalog identity when the title
    itself is an exact family alias.
    """
    candidate_text = _catalog_clean_text(
        _catalog_product_text(product)
    )
    if not candidate_text:
        return False

    family_brand = _catalog_clean_text(family.get("brand"))
    if family_brand:
        candidate_text = re.sub(
            rf"\b{re.escape(family_brand)}\b",
            " ",
            candidate_text,
            flags=re.I,
        )
        candidate_text = re.sub(
            r"\s+",
            " ",
            candidate_text,
        ).strip()

    candidate_key = catalog_variant_key(candidate_text)
    candidate_concentration = _catalog_concentration(
        _catalog_product_text(product)
    )

    for variant in family.get("variants", []):
        for alias in variant.get("aliases", []):
            alias_clean = _catalog_clean_text(alias)
            if not alias_clean:
                continue

            alias_concentration = _catalog_concentration(alias)
            if alias_concentration and candidate_concentration != alias_concentration:
                continue

            if candidate_key in _catalog_alias_keys(alias_clean):
                return True

    return False


def _catalog_brand_matches(
    product: Dict[str, Any],
    family: Dict[str, Any],
) -> bool:
    expected_brand = catalog_norm(
        family.get("brand")
    )

    if not expected_brand:
        return True

    actual_brand = product_field(
        product,
        "brand",
        "source_brand",
    )

    source = product.get("source")
    if isinstance(source, dict) and not actual_brand:
        actual_brand = str(
            source.get("brand")
            or source.get("source_brand")
            or ""
        ).strip()

    if not actual_brand:
        return True

    actual_brand_norm = catalog_norm(actual_brand)
    if actual_brand_norm == expected_brand:
        return True

    # A retailer can expose a product-line/marketing label in the brand
    # field instead of the manufacturer's canonical brand (for example a
    # product name used as a brand). That field must not block an otherwise
    # exact Family Registry identity. At the same time, a known catalog brand
    # belonging to another family is strong contrary evidence and must block
    # the match.
    known_registry_brands = {
        catalog_norm(item.get("brand"))
        for item in FAMILY_REGISTRY
        if catalog_norm(item.get("brand"))
    }
    if actual_brand_norm in known_registry_brands:
        return False

    return _catalog_title_matches_family_variant(
        product,
        family,
    )


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


def _catalog_product_is_excluded(
    product: Dict[str, Any],
    family: Dict[str, Any],
) -> bool:
    """Return True when a cataloged family explicitly excludes the product."""
    excluded = family.get("excluded") or []
    if not excluded:
        return False

    candidate_text = _catalog_clean_text(
        _catalog_product_text(product)
    )
    if not candidate_text:
        return False

    # Exclusions are catalog knowledge, so compare the title with the
    # family brand removed as well. Retailers commonly prefix the product
    # with the manufacturer (e.g. "Rasasi - Hawas Al Wisam Absolute").
    family_brand = _catalog_clean_text(family.get("brand"))
    candidate_without_brand = candidate_text
    if family_brand:
        candidate_without_brand = re.sub(
            rf"\b{re.escape(family_brand)}\b",
            " ",
            candidate_without_brand,
            flags=re.I,
        )
        candidate_without_brand = re.sub(
            r"\s+",
            " ",
            candidate_without_brand,
        ).strip()

    candidate_keys = {
        catalog_variant_key(candidate_text),
        catalog_variant_key(candidate_without_brand),
    }

    return any(
        catalog_variant_key(_catalog_clean_text(value)) in candidate_keys
        for value in excluded
        if _catalog_clean_text(value)
    )


def _catalog_variant_for_product(
    product: Dict[str, Any],
    family: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Identifica una sola variante autorizzata del catalogo.

    Il candidato deve corrispondere ESATTAMENTE a una delle forme
    autorizzate dopo la rimozione dei soli elementi commerciali
    (formato/concentrazione/spray). Questo impedisce che un titolo
     venga promosso semplicemente perché contiene il solo nome della
     famiglia senza una variante autorizzata.
    """
    if not _catalog_brand_matches(product, family):
        return None

    if _catalog_product_is_excluded(product, family):
        return None

    candidate_text = _catalog_clean_text(
        _catalog_product_text(product)
    )

    if not candidate_text:
        return None

    # Rimuove soltanto il brand della famiglia dal titolo candidato.
    brand = _catalog_clean_text(
        family.get("brand")
    )
    if brand:
        candidate_text = re.sub(
            rf"\b{re.escape(brand)}\b",
            " ",
            candidate_text,
            flags=re.I,
        )
        candidate_text = re.sub(
            r"\s+",
            " ",
            candidate_text,
        ).strip()

    candidate_key = catalog_variant_key(candidate_text)
    candidate_concentration = _catalog_concentration(
        _catalog_product_text(product)
    )

    for variant in family.get("variants", []):
        for alias in variant.get("aliases", []):
            alias_clean = _catalog_clean_text(alias)

            if not alias_clean:
                continue

            alias_concentration = _catalog_concentration(alias)

            # If the catalog variant explicitly distinguishes concentration,
            # that concentration is part of the identity. If the catalog
            # variant does not specify one, concentration remains commercial
            # metadata and may differ on the retailer title.
            if alias_concentration:
                if candidate_concentration != alias_concentration:
                    continue

            if candidate_key in _catalog_alias_keys(alias_clean):
                return variant

    return None


def _catalog_family_for_query(
    query: str,
) -> Optional[Dict[str, Any]]:
    query_clean = _catalog_clean_text(query)

    if not query_clean:
        return None

    for family in FAMILY_REGISTRY:
        for alias in family.get("query_aliases", []):
            alias_clean = _catalog_clean_text(alias)

            if not alias_clean:
                continue

            if _catalog_phrase_equal(
                query_clean,
                alias_clean,
            ):
                return family

            # Una query che contiene una famiglia catalogata ma aggiunge
            # una variante non presente nel registro resta sotto il
            # controllo del catalogo e NON torna al matching generico.
            if _catalog_phrase_in_text(
                alias_clean,
                query_clean,
            ):
                return family

    return None


def _catalog_requested_variant(
    query: str,
    family: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    query_clean = _catalog_clean_text(query)

    brand = _catalog_clean_text(
        family.get("brand")
    )
    if brand:
        query_clean = re.sub(
            rf"\b{re.escape(brand)}\b",
            " ",
            query_clean,
            flags=re.I,
        )
        query_clean = re.sub(
            r"\s+",
            " ",
            query_clean,
        ).strip()

    query_key = catalog_variant_key(query_clean)
    query_concentration = _catalog_concentration(query)

    for variant in family.get("variants", []):
        for alias in variant.get("aliases", []):
            alias_clean = _catalog_clean_text(alias)
            alias_key = catalog_variant_key(alias_clean)

            if alias_key != query_key:
                continue

            alias_concentration = _catalog_concentration(alias)

            if alias_concentration:
                if query_concentration != alias_concentration:
                    continue

            return variant

    return None


def _catalog_match(
    product: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    """
    Restituisce la variante catalogata del candidato, oppure None.

    Il catalogo è autoritativo soltanto per le famiglie che dichiara.
    Per tutte le altre famiglie resta attiva la validazione generica.
    """
    if not FAMILY_REGISTRY:
        return None

    query_clean = _catalog_clean_text(query)
    if not query_clean:
        return None

    for family in FAMILY_REGISTRY:
        variant = _catalog_variant_for_product(
            product,
            family,
        )

        if variant is None:
            continue

        # Query famiglia: tutte e sole le varianti catalogate.
        # Qui usiamo il confronto ESATTO con query_aliases. Una query
        # una query che aggiunge una variante non catalogata è invece una
        # query della famiglia ma non una query-famiglia: deve passare dalla
        # variante richiesta e,
        # se non esiste nel catalogo, essere respinta.
        query_is_family = any(
            _catalog_phrase_equal(
                query_clean,
                alias,
            )
            for alias in family.get("query_aliases", [])
        )

        if query_is_family:
            result = dict(product)
            result["name"] = variant["canonical_name"]
            result["canonical_name"] = variant["canonical_name"]
            result["family_id"] = family.get("family_id", "")
            result["brand"] = str(family.get("brand") or "").strip()
            result["canonical_brand"] = result["brand"]
            result["family_name"] = (
                family.get("query_aliases", [""])[0]
                if family.get("query_aliases")
                else ""
            )
            result["catalog_variant"] = variant["canonical_name"]
            return result

        # Query variante: solo quella specifica.
        requested = _catalog_requested_variant(
            query,
            family,
        )

        if requested is variant:
            result = dict(product)
            result["name"] = variant["canonical_name"]
            result["canonical_name"] = variant["canonical_name"]
            result["family_id"] = family.get("family_id", "")
            result["brand"] = str(family.get("brand") or "").strip()
            result["canonical_brand"] = result["brand"]
            result["family_name"] = (
                family.get("query_aliases", [""])[0]
                if family.get("query_aliases")
                else ""
            )
            result["catalog_variant"] = variant["canonical_name"]
            return result

    return None


# ============================================================
# VALIDAZIONE
# ============================================================

def _matching_text(product: Dict[str, Any]) -> str:
    """
    Costruisce il testo identitario usato dal matcher centrale.

    La fonte primaria resta il nome prodotto. Quando il nome dello scraper
    è incompleto, vengono usati anche titolo/product_name, brand, product_line,
    variant e URL già presenti nel candidate. Non viene introdotta alcuna
    conoscenza specifica di marca o profumo.
    """
    values: List[str] = []

    for key in (
        "name",
        "title",
        "product_name",
        "brand",
        "source_brand",
        "product_line",
        "variant",
        "url",
    ):
        value = product.get(key)
        if value not in (None, ""):
            values.append(str(nested_value(value)))

    source = product.get("source")
    if isinstance(source, dict):
        for key in (
            "name",
            "title",
            "product_name",
            "brand",
            "source_brand",
        ):
            value = source.get(key)
            if value not in (None, ""):
                values.append(str(nested_value(value)))

    return norm(" ".join(values))


def _matching_tokens(value: Any) -> List[str]:
    """Tokenizzazione identitaria, senza eliminare varianti di genere."""
    text = norm(value)
    if not text:
        return []

    # Rimuove soltanto formato/concentrazione/dati commerciali.
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|"
        r"eau\s+de\s+cologne|eau\s+fraiche|"
        r"extrait\s+de\s+parfum|edp|edt|edc|"
        r"parfum|perfume|spray)\b",
        " ",
        text,
        flags=re.I,
    )

    return [
        token
        for token in re.sub(r"\s+", " ", text).strip().split()
    ]


def _phrase_tokens_in_sequence(
    phrase_tokens: List[str],
    candidate_tokens: List[str],
) -> bool:
    if not phrase_tokens or not candidate_tokens:
        return False

    width = len(phrase_tokens)
    if width > len(candidate_tokens):
        return False

    # First choice: exact contiguous identity. This is what makes a base
    # query match all of its variants while a specific variant stays exact.
    for index in range(len(candidate_tokens) - width + 1):
        if candidate_tokens[index:index + width] == phrase_tokens:
            return True

    return False


def _generic_match(product: Dict[str, Any], query: str) -> bool:
    """
    Matching universale basato sulla frase identitaria.

    Regola fondamentale:
      - query base "Eros" -> Eros, Eros Flame, Eros Energy, ...
      - query specifica "Eros Flame" -> solo Eros Flame
      - query "9 PM" -> 9 PM, 9 PM Elixir, 9 PM Rebel, 9 PM Pour Femme, ...
      - query "9 PM Pour Femme" -> solo quella variante.

    Non esiste alcun elenco di varianti. La distinzione nasce dalla query
    stessa e dalla sequenza delle parole realmente presenti nel candidato.
    """
    query_tokens = _matching_tokens(query)
    candidate_tokens = _matching_tokens(
        _matching_text(product)
    )

    if not query_tokens or not candidate_tokens:
        return False

    return _phrase_tokens_in_sequence(
        query_tokens,
        candidate_tokens,
    )


def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Validazione centrale generica.

    Il Family Registry può canonicalizzare dati che conosce, ma NON può
    limitare la discovery alle sole famiglie presenti nel Registry. Tutte
    le famiglie, comprese quelle mai viste prima, passano quindi dallo
    stesso matcher universale.
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

    if not name and not _matching_text(product):
        return False

    query_has_size = bool(
        re.search(
            r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
            query_normalized,
        )
    )

    if has_small_size(product) and not query_has_size:
        return False

    # If the user explicitly searches a concentration, it is part of the
    # requested identity. A candidate with a different explicit concentration
    # must not pass (e.g. Eros Pour Femme EDT vs EDP).
    requested_concentration = product_concentration(
        {"name": query}
    )
    candidate_concentration = product_concentration(product)

    if (
        requested_concentration
        and candidate_concentration
        and requested_concentration != candidate_concentration
    ):
        return False

    matching_text = _matching_text(product)
    query_text = norm(query)

    # Prodotti commerciali non pertinenti: vengono filtrati solo quando
    # la query stessa non li richiede esplicitamente.
    for phrase in NON_PERFUME:
        phrase_normalized = norm(phrase)
        if (
            phrase_normalized in matching_text
            and phrase_normalized not in query_text
        ):
            return False

    return _generic_match(
        product,
        query,
    )


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

            # Deduplica il medesimo candidato proveniente da tentativi di
            # discovery diversi PRIMA delle operazioni costose (prezzo,
            # immagine). La chiave resta quella generale già usata dal
            # sistema e non elimina varianti diverse.
            key = product_identity_key(product)

            if key in seen:
                continue

            seen.add(key)

            product = resolve_actual_price(product)

            image = product_image(product)
            if image:
                product["image"] = image

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


def _display_cleanup(value: Any) -> str:
    """Rimuove solo elementi commerciali dal nome destinato alla UI."""
    text = str(value or "").strip()
    if not text:
        return ""

    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|"
        r"eau\s+de\s+cologne|eau\s+fraiche|"
        r"extrait\s+de\s+parfum|edp|edt|edc|"
        r"parfum|perfume|spray)\b",
        " ",
        text,
        flags=re.I,
    )
    text = re.sub(r"\s+", " ", text).strip(" -|/")
    return text


def _display_identity_tokens(value: Any) -> List[tuple]:
    """Return normalized/original token pairs for stable UI naming."""
    cleaned = _display_cleanup(value)
    if not cleaned:
        return []

    pairs = []
    for original in cleaned.split():
        normalized = norm(original)
        if not normalized:
            continue
        for token in normalized.split():
            pairs.append((token, original))

    return pairs


def _generic_display_name(
    product: Dict[str, Any],
    query: str,
) -> str:
    """Create a stable display name using only observed product text."""
    raw_name = product_field(
        product,
        "name",
        "title",
        "product_name",
    )
    if not raw_name:
        source = product.get("source")
        if isinstance(source, dict):
            raw_name = str(
                source.get("name")
                or source.get("title")
                or ""
            ).strip()

    cleaned_name = _display_cleanup(raw_name)
    query_clean = _display_cleanup(query)

    if not cleaned_name:
        return query_clean

    query_pairs = _display_identity_tokens(query_clean)
    name_pairs = _display_identity_tokens(cleaned_name)
    query_tokens = [pair[0] for pair in query_pairs]
    name_tokens = [pair[0] for pair in name_pairs]

    if not query_tokens or not name_tokens:
        return cleaned_name

    width = len(query_tokens)
    for index in range(len(name_tokens) - width + 1):
        if name_tokens[index:index + width] != query_tokens:
            continue

        suffix_original = [
            original
            for _, original in name_pairs[index + width:]
        ]

        # Preserve the user's spelling for the searched identity and the
        # retailer's original spelling for the concrete variant suffix.
        result = " ".join(
            query_clean.split() + suffix_original
        ).strip()
        if result:
            return result

    return cleaned_name


def _apply_generic_display_name(
    product: Dict[str, Any],
    query: str,
) -> Dict[str, Any]:
    item = dict(product)
    display_name = _generic_display_name(item, query)

    if display_name:
        item["display_name"] = display_name

    return item


def _validate_candidate(
    product: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    if not matches(product, query):
        return None

    # Quando una famiglia è catalogata, restituisce anche la versione
    # canonicalizzata del candidato. Per le famiglie non catalogate il
    # prodotto originale resta invariato.
    catalog_product = _catalog_match(
        product,
        query,
    )

    if catalog_product is not None:
        return catalog_product

    # Once a query resolves to an authoritative Family Registry family,
    # generic matching is not allowed to invent/merge variants that the
    # registry does not recognize. This is what prevents:
    #   - Hawas Al Wisam / Daarej from appearing under "Hawas"
    #   - bare "Hawas Eau de Parfum" from becoming both Him and Her.
    family = _catalog_family_for_query(query)
    if family is not None:
        return None

    return _apply_generic_display_name(
        product,
        query,
    )


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

def _propagate_catalog_identity(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Propaga l'identità Family Registry già riconosciuta dai candidati
    catalogati ai candidati fallback che rappresentano la stessa variante.

    Regola generica:
      - usa esclusivamente le identità catalogate presenti nello stesso
        risultato della ricerca;
      - confronta la variante canonica con il testo identitario del fallback;
      - quando più varianti sono compatibili, sceglie quella con la
        corrispondenza più lunga;
      - non dipende da marca o profumo specifici.
    """
    if not products:
        return products

    catalog_anchors: List[Dict[str, Any]] = []

    for product in products:
        family_id = str(product.get("family_id") or "").strip()
        catalog_variant = str(
            product.get("catalog_variant")
            or product.get("canonical_name")
            or ""
        ).strip()

        if not family_id or not catalog_variant:
            continue

        catalog_anchors.append(product)

    if not catalog_anchors:
        return products

    # Deduplicate anchors by canonical family + variant.
    anchors_by_key: Dict[tuple, Dict[str, Any]] = {}
    for product in catalog_anchors:
        key = (
            norm(product.get("family_id")),
            norm(product.get("catalog_variant")),
        )
        anchors_by_key.setdefault(key, product)

    anchors = list(anchors_by_key.values())

    output: List[Dict[str, Any]] = []

    for product in products:
        if (
            str(product.get("family_id") or "").strip()
            and str(product.get("catalog_variant") or "").strip()
        ):
            output.append(product)
            continue

        candidate_text = _matching_text(product)
        candidate_tokens = _matching_tokens(candidate_text)

        if not candidate_tokens:
            output.append(product)
            continue

        best_anchor: Optional[Dict[str, Any]] = None
        best_score = 0

        for anchor in anchors:
            variant = str(
                anchor.get("catalog_variant")
                or anchor.get("canonical_name")
                or ""
            ).strip()

            # Use the canonical variant AND every explicit alias registered
            # for this exact family/variant. Retailers often omit/reorder
            # "for her", accents, apostrophes, etc.
            family_id = str(anchor.get("family_id") or "").strip()
            alias_values: List[str] = [variant]

            if family_id:
                for family in FAMILY_REGISTRY:
                    if str(family.get("family_id") or "").strip() != family_id:
                        continue

                    for registry_variant in family.get("variants", []):
                        registry_name = str(
                            registry_variant.get("canonical_name") or ""
                        ).strip()

                        if norm(registry_name) != norm(variant):
                            continue

                        for alias in registry_variant.get("aliases", []):
                            alias = str(alias or "").strip()
                            if alias:
                                alias_values.append(alias)
                        break

                    break

            # The longest matching alias wins. This keeps more specific
            # variants from being captured by shorter family names.
            best_alias_score = 0
            for alias in dict.fromkeys(alias_values):
                alias_matches = _catalog_alias_keys(alias)
                if not alias_matches:
                    continue

                for alias_key in alias_matches:
                    alias_tokens = _matching_tokens(alias_key)
                    if not alias_tokens:
                        continue

                    if not _phrase_tokens_in_sequence(
                        alias_tokens,
                        candidate_tokens,
                    ):
                        continue

                    alias_score = len(alias_tokens)
                    if alias_score > best_alias_score:
                        best_alias_score = alias_score

            if best_alias_score == 0:
                continue

            score = best_alias_score

            anchor_concentration = product_concentration(anchor)
            candidate_concentration = product_concentration(product)

            if (
                anchor_concentration
                and candidate_concentration
                and anchor_concentration != candidate_concentration
            ):
                continue

            if score > best_score:
                best_score = score
                best_anchor = anchor

        if best_anchor is None:
            output.append(product)
            continue

        item = dict(product)
        item["name"] = best_anchor.get(
            "name",
            item.get("name", ""),
        )
        item["canonical_name"] = best_anchor.get("canonical_name") or best_anchor.get("catalog_variant", "")
        item["family_id"] = best_anchor.get(
            "family_id",
            "",
        )
        item["brand"] = best_anchor.get(
            "brand",
            item.get("brand", ""),
        )
        item["canonical_brand"] = best_anchor.get(
            "canonical_brand",
            best_anchor.get("brand", ""),
        )
        item["family_name"] = best_anchor.get(
            "family_name",
            "",
        )
        item["catalog_variant"] = best_anchor.get(
            "catalog_variant",
            best_anchor.get("canonical_name", ""),
        )

        output.append(item)

    return output


def _catalog_result_group_key(product: Dict[str, Any]) -> Optional[tuple]:
    """
    Canonical identity for the final product card.

    Retailer IDs remain offer-level identifiers; once catalog matching has
    resolved family_id + catalog_variant, they must not create separate
    product cards.
    """
    family_id = str(product.get("family_id") or "").strip()
    variant = str(
        product.get("catalog_variant")
        or product.get("canonical_name")
        or ""
    ).strip()

    if not family_id or not variant:
        return None

    return (
        "catalog",
        norm(family_id),
        norm(variant),
    )


def _group_catalog_results(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    One card per canonical catalog variant, preserving all retailer offers.

    The cheapest offer remains the primary top-level offer for backward
    compatibility. All offers are also exposed in `offers`.
    """
    if not products:
        return []

    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    uncataloged: List[Dict[str, Any]] = []

    for product in products:
        key = _catalog_result_group_key(product)
        if key is None:
            uncataloged.append(product)
            continue

        groups.setdefault(key, []).append(product)

    output: List[Dict[str, Any]] = []

    for items in groups.values():
        offers = unique_results(items)
        offers = sorted(offers, key=deterministic_result_key)

        if not offers:
            continue

        primary = dict(offers[0])
        primary["offers"] = [dict(offer) for offer in offers]
        primary["offer_count"] = len(offers)
        output.append(primary)

    output.extend(unique_results(uncataloged))
    return sort_by_price(output)


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

    validated = _propagate_catalog_identity(
        validated,
    )

    return _group_catalog_results(validated)

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

        # IMPORTANT:
        # non ricalcolare la validazione dell'intero candidate pool ogni
        # volta che termina uno store. I candidati già validati non cambiano
        # quando arriva un altro store. Validiamo quindi solo il nuovo lotto
        # e poi lo fondiamo con i risultati già ottenuti.
        with SEARCH_JOBS_LOCK:
            job = SEARCH_JOBS.get(job_id)

            if job is None:
                return

            job["candidates"].extend(
                store_candidates
            )
            existing_results = list(
                job["results"]
            )

        new_candidates = unique_results(
            store_candidates
        )

        ranked_candidates = _pre_rank_candidates(
            new_candidates,
            query,
        )

        new_results = _validate_candidates_parallel(
            ranked_candidates,
            query,
        )

        combined_results = _propagate_catalog_identity(
            existing_results + new_results,
        )

        results = _group_catalog_results(
            combined_results
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
