from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import requests
import json
import os
import re
import traceback
import gc
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


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


def build_search_attempts(store: str, query: str) -> List[str]:
    """
    Restituisce una sola query per ogni scraper.

    Le vecchie versioni generavano query aggiuntive (query compatta
    e singoli termini per Bplatz). Questo moltiplicava le richieste
    HTTP, aumentando il rischio di 403/429 e il consumo di memoria.
    La normalizzazione e la logica specifica del singolo negozio
    restano responsabilità dello scraper.
    """
    return [query]


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    """
    Esegue la ricerca su un singolo negozio.
    """
    module = load_scraper(store)

    attempts = build_search_attempts(
        store,
        query,
    )

    output: List[Dict[str, Any]] = []
    seen = set()

    for attempt in attempts:

        results = module.search(attempt) or []

        for item in results:

            if not isinstance(item, dict):
                continue

            product = dict(item)

            product.setdefault(
                "store",
                store,
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
# DEBUG - DELOOX RAW CATEGORY
# ============================================================

@app.get("/debug-deloox-raw")
def debug_deloox_raw(
    q: str = "Liquid Brun Limited édition",
):
    try:
        module = load_scraper("deloox")
        session = requests.Session()

        category_url = module._find_brand_category(
            session,
            q,
        )

        if not category_url:
            return {
                "query": q,
                "category_url": None,
                "error": "category not found",
            }

        response = module._get(
            session,
            category_url,
        )

        if response is None:
            return {
                "query": q,
                "category_url": category_url,
                "error": "category request failed",
            }

        html = response.text or ""
        html_lower = html.lower()

        markers = [
            "limited",
            "edition",
            "édition",
            "extrait",
            "150 ml",
            "liquid brun",
            "42,89",
            "42.89",
        ]

        return {
            "query": q,
            "category_url": category_url,
            "status_code": response.status_code,
            "html_length": len(html),
            "marker_counts": {
                marker: html_lower.count(
                    marker.lower()
                )
                for marker in markers
            },
        }

    except Exception as error:
        return {
            "query": q,
            "error": f"{type(error).__name__}: {error}",
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
        }

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    # IMPORTANTE: eseguiamo gli scraper uno alla volta.
    # Il piano Free di Render dispone di 512 MB di RAM.
    # Eseguire 8 scraper contemporaneamente fa crescere molto la memoria
    # perché ogni scraper può caricare HTML e BeautifulSoup nello stesso momento.
    # La versione precedente del backend era sequenziale e funzionava.
    for store in STORES:
        store_results = []
        try:
            store_results = run_store(store, query)
            all_results.extend(store_results)
        except Exception as error:
            errors[store] = f"{type(error).__name__}: {error}"
            traceback.print_exc()
        finally:
            # Rilascia subito i riferimenti temporanei dello scraper.
            store_results.clear()
            del store_results
            gc.collect()

    results = unique_results(all_results)
    results = sort_by_price(results)

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }


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
