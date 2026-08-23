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


def _validate_candidate(
    product: Dict[str, Any],
    query: str,
) -> Optional[Dict[str, Any]]:
    if not matches(product, query):
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
