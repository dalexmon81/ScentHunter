from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed


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

BLOCKED_STORES = {"notino", "perfumemarket", "parfumcity"}
ACTIVE_STORES = [store for store in STORES if store not in BLOCKED_STORES]

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

def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Evita risultati palesemente diversi dalla ricerca.

    Esempio:
    se si cerca "9 PM", non devono entrare automaticamente
    "9 PM Rebel", "9 PM Elixir", ecc.
    """
    name = norm(product.get("name", ""))
    query_normalized = norm(query)

    if not name:
        return False

    for phrase in VARIANTS:
        normalized_phrase = norm(phrase)

        if (
            normalized_phrase in name
            and normalized_phrase not in query_normalized
        ):
            return False

    for phrase in NON_PERFUME:
        normalized_phrase = norm(phrase)

        if (
            normalized_phrase in name
            and normalized_phrase not in query_normalized
        ):
            return False

    tokens = [
        token
        for token in query_normalized.split()
        if token not in IGNORED_WORDS
    ]

    if not tokens:
        return False

    return all(
        token in name
        for token in tokens
    )


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


def build_search_attempts(query: str) -> List[str]:
    query = str(query or "").strip()
    return [query] if query else []


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    module = load_scraper(store)
    output: List[Dict[str, Any]] = []
    seen = set()

    for attempt in build_search_attempts(query):
        results = module.search(attempt) or []

        if not isinstance(results, list):
            return output

        for item in results:
            if not isinstance(item, dict):
                continue

            product = dict(item)
            product.setdefault("store", store)

            key = (
                str(product.get("url", "")).lower(),
                norm(product.get("name", "")),
            )

            if key in seen:
                continue

            seen.add(key)

            if matches(product, query):
                output.append(product)

            if len(output) >= 10:
                return output

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
        return {
            "query": "",
            "count": 0,
            "results": [],
            "errors": {},
            "message": "Inserisci il nome di un profumo.",
        }

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    # Massimo 3 scraper contemporaneamente.
    # 8 in parallelo causano picchi di RAM; tutti in sequenza possono
    # superare il timeout di 90 secondi del frontend.
    max_workers = min(3, len(ACTIVE_STORES))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_store, store, query): store
            for store in ACTIVE_STORES
        }

        for future in as_completed(futures):
            store = futures[future]
            try:
                store_results = future.result()
                all_results.extend(store_results)
                logger.info(
                    "SEARCH store=%s results=%s",
                    store,
                    len(store_results),
                )
            except Exception as error:
                errors[store] = f"{type(error).__name__}: {error}"
                logger.warning(
                    "SEARCH store=%s ERROR=%s",
                    store,
                    error,
                )

    results = sort_by_price(unique_results(all_results))

    for store in sorted(BLOCKED_STORES):
        errors.setdefault(
            store,
            "Temporaneamente escluso: il sito sta rispondendo 403/429."
        )

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
        "message": (
            ""
            if results
            else "Nessun risultato disponibile al momento."
        ),
    }


# ============================================================
# API - SUGGEST / AUTOCOMPLETE
# ============================================================

AUTOCOMPLETE_CATALOG = [
    {"brand": "Rasasi", "name": "Hawas for Him", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Ice", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Black", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Tropical", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Fire", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Kobra", "image": ""},
    {"brand": "Afnan", "name": "9 PM", "image": ""},
    {"brand": "Afnan", "name": "9 PM Rebel", "image": ""},
    {"brand": "Afnan", "name": "9 PM Elixir", "image": ""},
    {"brand": "Afnan", "name": "9 PM Night Out", "image": ""},
    {"brand": "French Avenue", "name": "Liquid Brun", "image": ""},
    {"brand": "French Avenue", "name": "Liquid Brun Limited Edition", "image": ""},
]

@app.get("/suggest")
def suggest(q: str):
    query = norm(q)
    if len(query) < 2:
        return {"query": q, "count": 0, "suggestions": [], "source": "local"}

    words = query.split()
    hits = []
    for item in AUTOCOMPLETE_CATALOG:
        haystack = norm(f"{item.get('brand','')} {item.get('name','')}")
        if all(word in haystack for word in words):
            name_n = norm(item.get("name",""))
            score = 0 if name_n.startswith(query) else (1 if query in name_n else 2)
            hits.append((score, len(item.get("name","")), item))

    hits.sort(key=lambda x:(x[0],x[1],x[2].get("name","").lower()))
    suggestions=[x[2] for x in hits[:8]]
    return {"query": q, "count": len(suggestions), "suggestions": suggestions, "source": "local"}

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
