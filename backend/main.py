from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import traceback
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


# ============================================================
# CORS
# ============================================================

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

# Parole che descrivono una variante del profumo.
# NON vengono usate per escludere il risultato: se l'utente cerca
# la famiglia (es. "Eros" o "9 PM"), tutte le varianti devono restare.
VARIANTS = {
    "pour femme",
    "night out",
    "rebel",
    "elixir",
    "intense",
    "extreme",
    "limited edition",
    "collector edition",
    "collector's edition",
}

# Questi termini indicano un prodotto diverso dal profumo.
# I set/cofanetti/kit sono gestiti separatamente e NON vengono esclusi.
NON_PERFUME = {
    "deodorant",
    "deo spray",
    "shampoo",
    "conditioner",
    "hair conditioner",
    "shower gel",
    "gel douche",
    "body wash",
    "hand wash",
    "body lotion",
    "body cream",
    "body creme",
    "hand cream",
    "hand creme",
    "cream",
    "creme",
    "crème",
    "lotion",
    "oil",
    "huile",
    "after shave",
    "aftershave",
    "soap",
    "savon",
    "balm",
    "baume",
    "serum",
    "sérum",
    "scrub",
    "cleanser",
    "mask",
    "emulsion",
    "émulsion",
    "candle",
    "diffuser",
    "room spray",
    "home fragrance",
}

SET_PRODUCTS = {
    "gift set",
    "set regalo",
    "coffret",
    "bundle",
    "travel set",
    "discovery set",
    "kit",
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


# ============================================================
# FUNZIONI DI NORMALIZZAZIONE
# ============================================================

def norm(value: Any) -> str:
    """
    Normalizza un nome per rendere più affidabili confronti e ricerche.

    Esempi:
        9PM   -> 9 pm
        9 PM  -> 9 pm
    """
    value = str(value or "").lower().strip()

    value = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        value,
    )

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def price_num(value: Any) -> Optional[float]:
    """
    Estrae il valore numerico da un prezzo.
    """
    match = re.search(
        r"(\d{1,5}(?:[.,]\d{1,2})?)",
        str(value or ""),
    )

    if not match:
        return None

    try:
        return float(
            match.group(1).replace(",", ".")
        )
    except ValueError:
        return None


def product_image(product: Dict[str, Any]) -> str:
    """
    Recupera l'immagine indipendentemente dal nome usato dallo scraper.
    """
    return (
        product.get("image")
        or product.get("image_url")
        or product.get("thumbnail")
        or ""
    )


# ============================================================
# NOME CANONICO / FILTRO RISULTATI
# ============================================================

CATALOG_PATH = os.path.join(
    BASE_DIR,
    "SCENTHUNTER CATALOGO CORRETTO.json",
)


CATALOG_BRANDS: Dict[str, str] = {}


def load_catalog_aliases() -> Dict[str, str]:
    """
    Legge il catalogo master, quando disponibile, per ricondurre gli alias
    dei negozi al nome canonico senza creare una lista manuale nel codice.
    """
    try:
        with open(CATALOG_PATH, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, ValueError, TypeError):
        return {}

    products = payload.get("products", []) if isinstance(payload, dict) else []
    aliases: Dict[str, str] = {}

    if not isinstance(products, list):
        return aliases

    for item in products:
        if not isinstance(item, dict):
            continue

        brand = str(item.get("brand") or "").strip()
        canonical = str(item.get("name") or "").strip()
        if not canonical:
            continue

        candidates = [canonical]
        candidates.extend(item.get("aliases") or [])

        # Se il nome canonico inizia con Uomo/Donna/Men/Women ma esiste
        # un alias con le stesse parole e il genere dopo il nome della famiglia,
        # preferiamo quest'ultimo ordine. Non contiene una lista manuale di profumi.
        preferred = canonical
        gender_prefixes = {
            "uomo",
            "donna",
            "men",
            "women",
            "man",
            "woman",
        }
        canonical_tokens = sorted(norm(canonical).split())
        if canonical_tokens:
            first_token = norm(canonical).split()[0]
            if first_token in gender_prefixes:
                for alias in candidates[1:]:
                    alias = str(alias or "").strip()
                    alias_tokens = sorted(norm(alias).split())
                    alias_first = norm(alias).split()[0] if norm(alias) else ""
                    if (
                        alias_tokens == canonical_tokens
                        and alias_first not in gender_prefixes
                    ):
                        preferred = alias
                        break

        # Rimuove un eventuale prefisso brand presente nell'alias scelto.
        preferred_n = norm(preferred)
        brand_n = norm(brand)
        if brand_n and preferred_n.startswith(brand_n + " "):
            preferred = preferred[len(brand):].lstrip(" -:")

        for candidate in candidates:
            candidate = str(candidate or "").strip()
            if not candidate:
                continue
            key = norm(candidate)
            aliases[key] = preferred
            if brand:
                aliases[norm(f"{brand} {candidate}")] = preferred

            if brand:
                CATALOG_BRANDS[key] = brand
                if brand:
                    CATALOG_BRANDS[norm(f"{brand} {candidate}")] = brand

    return aliases


CATALOG_ALIASES = load_catalog_aliases()


def canonical_product_brand(product: Dict[str, Any]) -> str:
    """Restituisce il brand canonico quando il catalogo riconosce l'alias."""
    raw_name = str(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
        or ""
    ).strip()
    brand = str(product.get("brand") or "").strip()
    return (
        CATALOG_BRANDS.get(norm(raw_name))
        or CATALOG_BRANDS.get(norm(f"{brand} {raw_name}"))
        or brand
    ).strip()


def canonical_product_name(product: Dict[str, Any]) -> str:
    """
    Restituisce il nome canonico del profumo.

    Prima usa gli alias del catalogo master; se il prodotto non è nel catalogo,
    mantiene il nome dello scraper, eliminando solo un eventuale prefisso
    identico al brand.
    """
    raw_name = str(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
        or ""
    ).strip()
    brand = str(product.get("brand") or "").strip()

    if not raw_name:
        return ""

    canonical = (
        CATALOG_ALIASES.get(norm(raw_name))
        or CATALOG_ALIASES.get(norm(f"{brand} {raw_name}"))
    )
    name = canonical or raw_name

    if canonical:
        raw_name = canonical

    if brand:
        brand_n = norm(brand)
        name_n = norm(name)
        if name_n.startswith(brand_n + " "):
            # Conserviamo la grafia originale dopo il prefisso brand.
            name = name[len(brand):].lstrip(" -:")

    name = name.strip()
    # Uniforma anche la grafia 9PM/9pm in 9 PM senza alterare il resto del nome.
    name = re.sub(
        r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)",
        " ",
        name,
    )
    return name.strip()


def is_non_perfume(product: Dict[str, Any]) -> bool:
    """
    Identifica cosmetici e prodotti corpo/capelli che non sono profumi.
    I set/cofanetti/kit vengono sempre mantenuti.
    """
    name = norm(
        " ".join(
            str(product.get(field) or "")
            for field in (
                "name",
                "title",
                "product_name",
                "category",
                "product_type",
                "type",
            )
        )
    )

    if not name:
        return True

    if any(norm(marker) in name for marker in SET_PRODUCTS):
        return False

    return any(norm(phrase) in name for phrase in NON_PERFUME)


def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Verifica che il prodotto appartenga alla ricerca.

    La query viene trattata come ricerca per famiglia: quindi una ricerca
    come "Eros", "9 PM", "Born in Roma" o "Stronger With You" accetta
    naturalmente tutte le varianti che contengono quella famiglia.
    """
    name = canonical_product_name(product)
    brand = str(product.get("brand") or "").strip()
    haystack = norm(f"{brand} {name}")
    query_normalized = norm(query)

    if not haystack or is_non_perfume(product):
        return False

    tokens = [
        token
        for token in query_normalized.split()
        if token not in IGNORED_WORDS
    ]

    if not tokens:
        return False

    return all(token in haystack for token in tokens)


# ============================================================
# SCRAPER
# ============================================================

def load_scraper(store: str):
    """
    Carica dinamicamente:
        scrapers/<store>/scraper.py
    """
    return importlib.import_module(
        f"scrapers.{store}.scraper"
    )


def build_search_attempts(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
) -> List[str]:
    """Costruisce query complementari senza fermarsi al primo risultato parziale."""
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()
        if value and norm(value) not in [norm(x) for x in attempts]:
            attempts.append(value)

    add(raw)
    tokens = [t for t in normalized.split() if t not in IGNORED_WORDS]

    if tokens:
        add(" ".join(tokens))

    if len(tokens) >= 2:
        add(" ".join(tokens[1:]))

    if len(tokens) >= 3:
        add(" ".join(tokens[-2:]))

    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )
    if compact != normalized:
        add(compact)

    for hint in catalog_hints or []:
        add(hint)

    return attempts[:6]


def run_store(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Esegue più strategie di ricerca sullo stesso negozio e unisce i risultati pertinenti."""
    module = load_scraper(store)
    attempts = build_search_attempts(store, query, catalog_hints)
    output: List[Dict[str, Any]] = []
    seen = set()

    for attempt in attempts:
        results = module.search(attempt) or []
        for item in results:
            if not isinstance(item, dict):
                continue
            product = dict(item)
            product.setdefault("store", store)
            product["brand"] = canonical_product_brand(product)
            product["name"] = canonical_product_name(product)
            product["display_name"] = (
                f"{product.get('brand', '').strip()} - {product['name']}"
                if str(product.get('brand') or '').strip()
                else product['name']
            )
            key = (
                str(product.get("url", "")).lower(),
                norm(product.get("name", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            if matches(product, query):
                output.append(product)

    return output


# ============================================================
# DEDUPLICAZIONE E ORDINAMENTO
# ============================================================

def unique_results(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    unique: List[Dict[str, Any]] = []
    seen = set()

    for product in products:

        key = (
            str(product.get("store", "")).lower(),
            str(product.get("url", "")).lower(),
            norm(product.get("name", "")),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(product)

    return unique


def sort_by_name(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Ordina rigorosamente per nome normalizzato, con tie-break deterministici."""
    return sorted(
        products,
        key=lambda product: (
            norm(product.get("name", "")),
            norm(product.get("brand", "")),
            str(product.get("url", "")).lower(),
        ),
    )


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

    point = {
        "date": datetime.now(
            timezone.utc
        ).isoformat(),

        "value": best_offer[
            "price_value"
        ],

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

        save_history(
            history_data
        )

    return history


# ============================================================
# API - ROOT
# ============================================================

@app.get("/", include_in_schema=False)
def root():
    if not FRONTEND_INDEX.exists():
        raise HTTPException(
            status_code=500,
            detail="frontend/index.html non trovato",
        )
    return FileResponse(FRONTEND_INDEX)


# ============================================================
# API - HEALTH
# ============================================================

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "stores": STORES,
    }


# ============================================================
# API - SEARCH
# ============================================================

@app.get("/search")
def search_perfume(q: str):
    query = str(q or "").strip()

    if not query:
        return {"query": "", "count": 0, "results": [], "errors": {}}

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    # Contesto catalogo: una sola chiamata per la query, usata come supporto
    # agli scraper quando il nome del prodotto è ambiguo o poco indicizzato.
    catalog_hints: List[str] = []
    try:
        catalog_items = fragella_search(query, 10)
        query_n = norm(query)
        for item in catalog_items:
            name = str(item.get("name") or "").strip()
            brand = str(item.get("brand") or "").strip()
            if not name:
                continue
            text = norm(f"{brand} {name}")
            if query_n and all(token in text for token in query_n.split()):
                if brand:
                    catalog_hints.append(f"{brand} {name}")
                catalog_hints.append(name)
    except Exception:
        catalog_hints = []

    # NON 8 insieme: su Render Free abbiamo osservato exit 137.
    # Due worker riducono nettamente RAM e connessioni simultanee.
    executor = ThreadPoolExecutor(max_workers=2)
    futures = {
        executor.submit(run_store, store, query, catalog_hints): store
        for store in STORES
    }

    try:
        for future in as_completed(futures, timeout=28):
            store = futures[future]
            try:
                all_results.extend(future.result())
            except Exception as error:
                errors[store] = f"{type(error).__name__}: {error}"
                traceback.print_exc()
    except TimeoutError:
        pass
    finally:
        for future, store in futures.items():
            if not future.done():
                if future.cancel():
                    errors[store] = "Non eseguito: limite tempo ricerca"
                else:
                    errors[store] = "Timeout: negozio troppo lento"
        executor.shutdown(wait=False, cancel_futures=True)

    results = sort_by_name(unique_results(all_results))

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }


# ============================================================
# API - TEST SINGOLO STORE (diagnostica)
# ============================================================

@app.get("/test-store")
def test_store(store: str, q: str):
    """
    Endpoint diagnostico: esegue UN SOLO scraper.
    Non modifica la normale ricerca /search.
    """
    store = str(store or "").strip().lower()
    query = str(q or "").strip()

    if store not in STORES:
        raise HTTPException(
            status_code=400,
            detail=f"Store non valido. Disponibili: {', '.join(STORES)}",
        )

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Parametro q mancante",
        )

    try:
        results = run_store(store, query)
        return {
            "store": store,
            "query": query,
            "count": len(results),
            "results": results,
        }
    except Exception as error:
        traceback.print_exc()
        return {
            "store": store,
            "query": query,
            "count": 0,
            "results": [],
            "error": f"{type(error).__name__}: {error}",
        }


# ============================================================
# API - SUGGEST
# ============================================================

def fragella_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Catalogo profumi indipendente dai negozi.
    Serve SOLO all'autocomplete: la ricerca prezzi resta affidata agli scraper.
    """
    api_key = os.getenv("FRAGELLA_API_KEY", "").strip()

    if not api_key:
        return []

    params = urlencode({
        "search": query,
        "limit": max(1, min(int(limit), 10)),
    })

    request = Request(
        f"https://api.fragella.com/api/v1/fragrances?{params}",
        headers={
            "x-api-key": api_key,
            "Accept": "application/json",
            "User-Agent": "ScentHunter/1.0",
        },
    )

    with urlopen(request, timeout=5) as response:
        payload = json.loads(
            response.read().decode("utf-8")
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

        output.append({
            "name": name,
            "brand": brand,
            "store": brand or "ScentHunter",
            "image": image,
            "catalog_id": (
                item.get("_id")
                or item.get("id")
            ),
        })

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
        name = str(item.get("name") or "").strip()
        brand = str(item.get("brand") or "").strip()

        if not name:
            continue

        name_n = norm(name)
        brand_n = norm(brand)
        text = norm(f"{brand} {name}")

        if tokens and not all(token in text for token in tokens):
            continue

        if is_non_perfume(item):
            continue

        key = (
            str(item.get("catalog_id") or "").strip()
            or f"{brand_n}|{name_n}"
        )

        if key in seen:
            continue

        seen.add(key)

        # Priorità:
        # 1) nome profumo che inizia esattamente con ciò che si scrive
        # 2) brand che inizia con ciò che si scrive
        # 3) query contenuta nel nome
        # 4) query contenuta nel brand
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

        ranked.append((
            priority,
            position,
            len(name_n),
            name_n,
            item,
        ))

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

    # --------------------------------------------------------
    # 1. CATALOGO PROFUMI
    # --------------------------------------------------------
    # Non dipende dai negozi. Quindi "Aquatica", "Liquid Brun",
    # "Hawas Ice", ecc. possono comparire anche se uno scraper
    # prezzi in quel momento è lento o non risponde.
    if len(query) >= 3:
        try:
            catalog_queries = [raw_query]

            # Per ricerche tipo "French Avenue Liquid Brun"
            # proviamo anche le parole significative.
            for token in query.split():
                if len(token) >= 3 and token not in catalog_queries:
                    catalog_queries.append(token)

            catalog_results: List[Dict[str, Any]] = []
            catalog_seen = set()

            for catalog_query in catalog_queries:
                for item in fragella_search(catalog_query, 10):
                    key = (
                        str(item.get("catalog_id") or "").strip()
                        or f"{norm(item.get('brand'))}|{norm(item.get('name'))}"
                    )

                    if key in catalog_seen:
                        continue

                    catalog_seen.add(key)
                    catalog_results.append(item)

            suggestions = rank_catalog_suggestions(
                catalog_results,
                raw_query,
            )

            if suggestions:
                return {
                    "query": q,
                    "count": len(suggestions),
                    "suggestions": suggestions,
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

    # --------------------------------------------------------
    # 2. FALLBACK NEGOZI
    # --------------------------------------------------------
    # Se il catalogo esterno non è disponibile, manteniamo il
    # comportamento che già funzionava nel main(10).
    suggestions = []
    seen = set()

    for store in STORES:
        try:
            module = load_scraper(store)

            attempts = [raw_query]

            if query not in attempts:
                attempts.append(query)

            for attempt in attempts:
                if not attempt:
                    continue

                results = module.search(attempt) or []

                for product in results:
                    if not isinstance(product, dict):
                        continue

                    name = str(
                        product.get("name")
                        or product.get("title")
                        or product.get("product_name")
                        or ""
                    ).strip()

                    if not name:
                        continue

                    brand = str(
                        product.get("brand")
                        or ""
                    ).strip()
                    product = dict(product)
                    product["brand"] = canonical_product_brand(product)
                    brand = product["brand"]
                    product["name"] = canonical_product_name(product)
                    name = product["name"]
                    normalized_name = norm(name)

                    haystack = norm(
                        f"{brand} {name}"
                    )

                    words = [
                        word
                        for word in query.split()
                        if word
                    ]

                    if not all(
                        word in haystack
                        for word in words
                    ):
                        continue

                    if is_non_perfume(product):
                        continue

                    key = (
                        norm(brand),
                        normalized_name,
                    )

                    if key in seen:
                        continue

                    seen.add(key)

                    suggestions.append({
                        "name": name,
                        "display_name": (
                            f"{brand} - {name}"
                            if brand
                            else name
                        ),
                        "store": product.get(
                            "store",
                            store,
                        ),
                        "brand": brand,
                        "image": product_image(product),
                    })

        except Exception:
            traceback.print_exc()

    suggestions.sort(
        key=lambda item: (
            0
            if norm(item.get("name", "")).startswith(query)
            else 1,
            len(item.get("name", "")),
            item.get("name", "").lower(),
        )
    )

    suggestions = suggestions[:8]

    return {
        "query": q,
        "count": len(suggestions),
        "suggestions": suggestions,
        "source": "stores-fallback",
    }


# ============================================================
# API - AUTOCOMPLETE
# ============================================================

@app.get("/autocomplete")
def autocomplete(q: str):
    return suggest(q)


# ============================================================
# API - PRODUCT
# ============================================================

@app.get("/product")
def product(
    name: str,
    brand: str = "",
):

    data = search_perfume(
        name
    )

    offers: List[Dict[str, Any]] = []

    for product_data in data["results"]:

        value = price_num(
            product_data.get("price")
        )

        if value is None:
            continue

        offer = dict(
            product_data
        )

        offer["price_value"] = value
        offer["image"] = product_image(
            offer
        )

        offers.append(
            offer
        )

    offers.sort(
        key=lambda offer: offer[
            "price_value"
        ]
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
