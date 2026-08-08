from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import importlib
import json
import logging
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("scenthunter")

app = FastAPI(title="ScentHunter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Mantiene la stessa struttura utilizzata dal backend precedente.
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
PROJECT_DIR = BASE_DIR.parent
HISTORY_PATH = BASE_DIR / "price_history.json"
FRONTEND_INDEX = PROJECT_DIR / "frontend" / "index.html"

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


# ---------------------------------------------------------------------------
# Normalizzazione e prezzi
# ---------------------------------------------------------------------------

def norm(value: Any) -> str:
    value = str(value or "").lower().strip()
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
    return str(
        product.get("image")
        or product.get("image_url")
        or product.get("thumbnail")
        or ""
    )


# ---------------------------------------------------------------------------
# Filtro risultati
# ---------------------------------------------------------------------------

def matches(product: Dict[str, Any], query: str) -> bool:
    name = norm(product.get("name", ""))
    query_normalized = norm(query)

    if not name or not query_normalized:
        return False

    for phrase in VARIANTS | NON_PERFUME:
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

    return bool(tokens) and all(
        token in name
        for token in tokens
    )


# ---------------------------------------------------------------------------
# Scraper
# ---------------------------------------------------------------------------

def load_scraper(store: str):
    return importlib.import_module(
        f"scrapers.{store}.scraper"
    )


def build_search_attempts(query: str) -> List[str]:
    """
    Usa una sola richiesta normale e, solo quando necessario, una variante
    compatta. Evita le ricerche sui singoli token che moltiplicavano le
    richieste verso i negozi e favorivano 403/429.
    """
    clean_query = str(query or "").strip()

    attempts = (
        [clean_query]
        if clean_query
        else []
    )

    normalized_query = norm(clean_query)

    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized_query,
    )

    if (
        compact
        and compact != clean_query
        and compact not in attempts
    ):
        attempts.append(compact)

    return attempts


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
            logger.warning(
                "SCRAPER %s ha restituito un formato non valido",
                store,
            )
            continue

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

        # La variante compatta viene usata soltanto se il primo tentativo
        # non ha prodotto nulla.
        if output:
            break

    return output


# ---------------------------------------------------------------------------
# Deduplicazione e ordinamento
# ---------------------------------------------------------------------------

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
    return sorted(
        products,
        key=lambda product: (
            price_num(product.get("price"))
            if price_num(product.get("price")) is not None
            else float("inf")
        ),
    )


# ---------------------------------------------------------------------------
# Storico prezzi
# ---------------------------------------------------------------------------

def load_history() -> Dict[str, Any]:
    try:
        with HISTORY_PATH.open(
            "r",
            encoding="utf-8",
        ) as file:
            data = json.load(file)

        return data if isinstance(data, dict) else {}

    except (
        OSError,
        ValueError,
        TypeError,
    ):
        return {}


def save_history(
    data: Dict[str, Any],
) -> None:
    try:
        HISTORY_PATH.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        temporary_path = HISTORY_PATH.with_suffix(".tmp")

        with temporary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                data,
                file,
                ensure_ascii=False,
                indent=2,
            )

        temporary_path.replace(HISTORY_PATH)

    except OSError as error:
        logger.warning(
            "Impossibile salvare lo storico prezzi: %s",
            error,
        )


def update_price_history(
    name: str,
    brand: str,
    best_offer: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    history_data = load_history()

    key = norm(
        f"{brand} {name}"
    ) or norm(name)

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
        "value": best_offer["price_value"],
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


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

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

    return FileResponse(FRONTEND_INDEX)


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "stores": STORES,
    }


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

    # Sequenziale per limitare RAM e richieste simultanee su Railway.
    for store in STORES:
        try:
            store_results = run_store(
                store,
                query,
            )

            all_results.extend(store_results)

            logger.info(
                "SEARCH store=%s results=%s",
                store,
                len(store_results),
            )

        except Exception as error:
            errors[store] = (
                f"{type(error).__name__}: {error}"
            )

            logger.exception(
                "Errore scraper %s",
                store,
            )

    results = sort_by_price(
        unique_results(all_results)
    )

    response = {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }

    if not results:
        response["message"] = (
            "Nessun risultato disponibile. "
            "I negozi potrebbero aver bloccato "
            "temporaneamente la richiesta."
        )
    else:
        response["message"] = ""

    return response


AUTOCOMPLETE_CATALOG = [
    {
        "brand": "Rasasi",
        "name": "Hawas for Him",
        "image": "",
    },
    {
        "brand": "Rasasi",
        "name": "Hawas Ice",
        "image": "",
    },
    {
        "brand": "Rasasi",
        "name": "Hawas Black",
        "image": "",
    },
    {
        "brand": "Rasasi",
        "name": "Hawas Tropical",
        "image": "",
    },
    {
        "brand": "Rasasi",
        "name": "Hawas Fire",
        "image": "",
    },
    {
        "brand": "Rasasi",
        "name": "Hawas Kobra",
        "image": "",
    },
    {
        "brand": "Afnan",
        "name": "9 PM",
        "image": "",
    },
    {
        "brand": "Afnan",
        "name": "9 PM Rebel",
        "image": "",
    },
    {
        "brand": "Afnan",
        "name": "9 PM Elixir",
        "image": "",
    },
    {
        "brand": "Afnan",
        "name": "9 PM Night Out",
        "image": "",
    },
    {
        "brand": "French Avenue",
        "name": "Liquid Brun",
        "image": "",
    },
    {
        "brand": "French Avenue",
        "name": "Liquid Brun Limited Edition",
        "image": "",
    },
]


def make_suggestions(
    q: str,
) -> Dict[str, Any]:
    query = norm(q)

    if len(query) < 2:
        return {
            "query": q,
            "count": 0,
            "suggestions": [],
            "source": "local",
        }

    words = query.split()
    hits = []

    for item in AUTOCOMPLETE_CATALOG:
        haystack = norm(
            f"{item['brand']} {item['name']}"
        )

        if all(
            word in haystack
            for word in words
        ):
            name_normalized = norm(
                item["name"]
            )

            score = (
                0
                if name_normalized.startswith(query)
                else (
                    1
                    if query in name_normalized
                    else 2
                )
            )

            hits.append(
                (
                    score,
                    len(item["name"]),
                    item,
                )
            )

    hits.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2]["name"].lower(),
        )
    )

    suggestions = [
        item[2]
        for item in hits[:8]
    ]

    return {
        "query": q,
        "count": len(suggestions),
        "suggestions": suggestions,
        "source": "local",
    }


@app.get("/suggest")
def suggest(q: str = ""):
    return make_suggestions(q)


@app.get("/autocomplete")
def autocomplete(q: str = ""):
    return make_suggestions(q)


@app.get("/product")
def product(
    name: str,
    brand: str = "",
):
    data = search_perfume(name)
    offers: List[Dict[str, Any]] = []

    for product_data in data["results"]:
        value = price_num(
            product_data.get("price")
        )

        if value is None:
            continue

        offer = dict(product_data)
        offer["price_value"] = value
        offer["image"] = product_image(offer)
        offers.append(offer)

    offers.sort(
        key=lambda offer: offer["price_value"]
    )

    best_offer = (
        offers[0]
        if offers
        else None
    )

    history = update_price_history(
        name,
        brand,
        best_offer,
    )

    image = next(
        (
            offer.get("image", "")
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
