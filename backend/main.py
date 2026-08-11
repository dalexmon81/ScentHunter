from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import traceback
import time
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

# Famiglie che alcuni motori dei negozi indicizzano come prodotti separati.
# Servono SOLO per la ricerca della famiglia, non cambiano le altre ricerche.
FAMILY_SEARCH_TERMS = {
    "9 pm": [
        "9 PM",
        "9 PM Pour Femme",
        "9 PM Elixir",
        "9 PM Night Out",
        "9 PM Rebel",
    ],
    "9 am": [
        "9 AM",
        "9 AM Pour Femme",
        "9 AM Dive",
    ],
    "le beau": [
        "Le Beau",
        "Le Beau Le Parfum",
        "Le Beau Paradise Garden",
    ],
}

NON_PERFUME = {
    "gift set",
    "set regalo",
    "coffret",
    "bundle",
    "deodorant",
    "deo spray",
    "shower gel",
    "body lotion",
    "after shave",
    "aftershave",
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
# FILTRO RISULTATI
# ============================================================

def match_details(product: Dict[str, Any], query: str) -> Dict[str, Any]:
    """
    Esegue lo stesso filtro di matches(), ma restituisce anche il motivo
    per cui un prodotto viene accettato o scartato.

    La diagnostica serve a distinguere:
      - prodotto non restituito dallo scraper;
      - prodotto restituito ma scartato dal main;
      - prodotto restituito e accettato dal main.
    """
    query_normalized = norm(query)

    searchable_parts = [
        product.get("brand", ""),
        product.get("name", ""),
        product.get("title", ""),
        product.get("product_name", ""),
    ]
    searchable = norm(" ".join(
        str(value or "") for value in searchable_parts
    ))

    if not searchable:
        return {"matched": False, "reason": "campi nome/brand/titolo vuoti"}

    name = norm(product.get("name", ""))

    query_variant = None
    for phrase in VARIANTS:
        normalized_phrase = norm(phrase)
        if normalized_phrase and normalized_phrase in query_normalized:
            query_variant = normalized_phrase
            break

    if query_variant:
        for phrase in VARIANTS:
            normalized_phrase = norm(phrase)
            if (
                normalized_phrase
                and normalized_phrase in name
                and normalized_phrase != query_variant
            ):
                return {
                    "matched": False,
                    "reason": f"variante diversa: '{normalized_phrase}'",
                }

    for phrase in NON_PERFUME:
        normalized_phrase = norm(phrase)
        if (
            normalized_phrase in searchable
            and normalized_phrase not in query_normalized
        ):
            return {
                "matched": False,
                "reason": f"prodotto non profumo: '{normalized_phrase}'",
            }

    tokens = [
        token
        for token in query_normalized.split()
        if token not in IGNORED_WORDS
    ]

    if not tokens:
        return {"matched": False, "reason": "query senza token utili"}

    missing = [token for token in tokens if token not in searchable]
    if missing:
        return {
            "matched": False,
            "reason": "token mancanti: " + ", ".join(missing),
        }

    return {"matched": True, "reason": "match accettato"}


def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Filtro principale. Mantiene esattamente la logica precedente;
    match_details() aggiunge soltanto le informazioni diagnostiche.
    """
    return bool(match_details(product, query)["matched"])


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


def build_search_attempts(store: str, query: str) -> List[str]:
    """Poche query mirate: precisa prima, poi più corta."""
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()
        if value and norm(value) not in [norm(x) for x in attempts]:
            attempts.append(value)

    add(raw)

    if normalized in FAMILY_SEARCH_TERMS:
        for term in FAMILY_SEARCH_TERMS[normalized]:
            add(term)
        return attempts

    tokens = [t for t in normalized.split() if t not in IGNORED_WORDS]

    # Spesso la prima parola è il marchio:
    # Rasasi Hawas for Him -> Hawas Him
    # Lattafa Asad Bourbon -> Asad Bourbon
    if len(tokens) >= 2:
        add(" ".join(tokens[1:]))

    # Query ancora più semplice per motori che lavorano male con nomi lunghi.
    if len(tokens) >= 3:
        add(" ".join(tokens[-2:]))
    elif tokens:
        add(" ".join(tokens))

    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )
    if compact != normalized:
        add(compact)

    return attempts[:3]

def _diagnostic_product(product: Dict[str, Any], match: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Riduce un prodotto alla parte utile per la diagnostica."""
    return {
        "brand": str(product.get("brand", "") or ""),
        "name": str(product.get("name", "") or ""),
        "title": str(product.get("title", "") or ""),
        "product_name": str(product.get("product_name", "") or ""),
        "price": str(product.get("price", "") or ""),
        "url": str(product.get("url", "") or ""),
        "stock": product.get("stock"),
        "availability": product.get("availability"),
        "available": product.get("available"),
        "match": match if match is not None else None,
    }


def run_store_diagnostic(
    store: str,
    query: str,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Esegue un singolo scraper e registra una traccia completa di diagnosi.
    La logica di ricerca/matching resta invariata.
    """
    store_started = time.monotonic()
    module = load_scraper(store)

    attempts = build_search_attempts(
        store,
        query,
    )

    output: List[Dict[str, Any]] = []
    seen = set()
    attempt_diagnostics: List[Dict[str, Any]] = []

    for attempt in attempts:
        attempt_started = time.monotonic()
        attempt_error = None

        try:
            results = module.search(attempt) or []
        except Exception as error:
            results = []
            attempt_error = f"{type(error).__name__}: {error}"

        raw_count = len(results) if isinstance(results, list) else 0
        matched_count = 0
        rejected_count = 0
        raw_products: List[Dict[str, Any]] = []
        rejected_products: List[Dict[str, Any]] = []

        if not isinstance(results, list):
            results = []

        for item in results:
            if not isinstance(item, dict):
                continue

            product = dict(item)
            product.setdefault("store", store)
            match = match_details(product, query)

            if len(raw_products) < 50:
                raw_products.append(_diagnostic_product(product, match))

            key = (
                str(product.get("url", "")).lower(),
                norm(product.get("name", "")),
            )

            if key in seen:
                continue

            seen.add(key)

            if match["matched"]:
                output.append(product)
                matched_count += 1
            else:
                rejected_count += 1
                if len(rejected_products) < 30:
                    rejected_products.append(
                        _diagnostic_product(product, match)
                    )

        attempt_diagnostics.append({
            "query_sent": attempt,
            "duration_ms": round((time.monotonic() - attempt_started) * 1000),
            "raw_count": raw_count,
            "matched_count": matched_count,
            "rejected_count": rejected_count,
            "raw_products_sample": raw_products,
            "rejected_products_sample": rejected_products,
            "error": attempt_error,
        })

        if output and norm(query) not in FAMILY_SEARCH_TERMS:
            break

    diagnostic = {
        "store": store,
        "query": query,
        "status": "error" if any(a.get("error") for a in attempt_diagnostics) and not output else "ok",
        "duration_ms": round((time.monotonic() - store_started) * 1000),
        "attempt_count": len(attempt_diagnostics),
        "attempts": attempt_diagnostics,
        "total_matched": len(output),
    }

    return output, diagnostic


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    """Compatibilità con gli endpoint diagnostici esistenti."""
    results, _ = run_store_diagnostic(store, query)
    return results


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


def sort_by_price(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    def key(product):
        value = price_num(
            product.get("price")
        )

        if value is None:
            return float("inf")

        return value

    return sorted(
        products,
        key=key,
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

    search_started = time.monotonic()
    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    diagnostics: Dict[str, Any] = {}

    # Tutti gli 8 scraper vengono avviati subito.
    executor = ThreadPoolExecutor(max_workers=len(STORES))
    future_started: Dict[Any, float] = {}
    futures = {}

    for store in STORES:
        future = executor.submit(run_store_diagnostic, store, query)
        futures[future] = store
        future_started[future] = time.monotonic()

    try:
        for future in as_completed(futures, timeout=28):
            store = futures[future]
            elapsed_ms = round((time.monotonic() - future_started[future]) * 1000)
            try:
                store_results, diagnostic = future.result()
                diagnostic["future_duration_ms"] = elapsed_ms
                diagnostic["future_status"] = "completed"
                all_results.extend(store_results)
                diagnostics[store] = diagnostic
            except Exception as error:
                errors[store] = f"{type(error).__name__}: {error}"
                diagnostics[store] = {
                    "store": store,
                    "query": query,
                    "status": "error",
                    "future_status": "completed_with_error",
                    "future_duration_ms": elapsed_ms,
                    "error": errors[store],
                }
                traceback.print_exc()
    except TimeoutError:
        pass
    finally:
        for future, store in futures.items():
            if future.done():
                # Il future puo' essere terminato proprio mentre scatta il timeout.
                # Per la diagnosi lo marchiamo separatamente, senza alterare il
                # comportamento dei risultati gia' raccolti sopra.
                if store not in diagnostics:
                    elapsed_ms = round((time.monotonic() - future_started[future]) * 1000)
                    try:
                        store_results, diagnostic = future.result()
                        diagnostic["future_duration_ms"] = elapsed_ms
                        diagnostic["future_status"] = "completed_after_wait_window"
                        diagnostics[store] = diagnostic
                    except Exception as error:
                        errors[store] = f"{type(error).__name__}: {error}"
                        diagnostics[store] = {
                            "store": store,
                            "query": query,
                            "status": "error",
                            "future_status": "completed_after_wait_window_error",
                            "future_duration_ms": elapsed_ms,
                            "error": errors[store],
                        }
                continue

            elapsed_ms = round((time.monotonic() - future_started[future]) * 1000)
            if future.cancel():
                errors[store] = "Non eseguito: limite tempo ricerca"
                diagnostics[store] = {
                    "store": store,
                    "query": query,
                    "status": "not_executed",
                    "future_status": "cancelled",
                    "future_duration_ms": elapsed_ms,
                    "error": errors[store],
                }
            else:
                errors[store] = "Timeout: negozio troppo lento"
                diagnostics[store] = {
                    "store": store,
                    "query": query,
                    "status": "timeout",
                    "future_status": "still_running",
                    "future_duration_ms": elapsed_ms,
                    "error": errors[store],
                }

        executor.shutdown(wait=False, cancel_futures=True)

    results = sort_by_price(unique_results(all_results))

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
        "diagnostics": diagnostics,
        "diagnostic_total_duration_ms": round((time.monotonic() - search_started) * 1000),
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
        results, diagnostic = run_store_diagnostic(store, query)
        return {
            "store": store,
            "query": query,
            "count": len(results),
            "results": results,
            "diagnostic": diagnostic,
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

        if any(
            norm(phrase) in name_n
            for phrase in NON_PERFUME
        ):
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

                    normalized_name = norm(name)
                    brand = str(
                        product.get("brand")
                        or ""
                    ).strip()

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

                    if any(
                        norm(phrase) in normalized_name
                        for phrase in NON_PERFUME
                    ):
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
