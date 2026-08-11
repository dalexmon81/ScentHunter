from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
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

# Queste sono SOLO famiglie che alcuni motori dividono in prodotti separati.
# Non vengono usate per filtrare i risultati.
FAMILY_SEARCH_TERMS = {
    "9 pm": [
        "9 PM",
        "9PM",
        "Afnan 9 PM",
    ],
    "9 am": [
        "9 AM",
        "9AM",
    ],
    "le beau": [
        "Le Beau",
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
# RICERCA
# ============================================================

# Tutti gli 8 store possono partire insieme.
# Il vecchio max_workers=2 creava una coda: con 8 store e timeout
# di 28 s alcuni negozi non arrivavano nemmeno a essere eseguiti.
SEARCH_WORKERS = min(len(STORES), 8)

# Limite complessivo della ricerca API.
# Deve essere più basso del vecchio 28 s per evitare una UX da "ricerca bloccata".
SEARCH_TIMEOUT = 20


# ============================================================
# NORMALIZZAZIONE
# ============================================================

def norm(value: Any) -> str:
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
    # Gli scraper possono restituire brand e nome separati.
    # Il controllo deve quindi usare il testo completo del prodotto.
    name = norm(product.get("name", ""))
    brand = norm(product.get("brand", ""))
    title = norm(product.get("title", ""))
    product_text = norm(" ".join(
        part for part in (brand, name, title) if part
    ))
    query_normalized = norm(query)

    if not product_text:
        return False

    query_variant = None

    for phrase in (
        "pour femme",
        "night out",
        "rebel",
        "elixir",
        "intense",
        "extreme",
        "limited edition",
        "collector edition",
        "collectors edition",
    ):
        normalized_phrase = norm(phrase)

        if (
            normalized_phrase
            and normalized_phrase in query_normalized
        ):
            query_variant = normalized_phrase
            break

    if query_variant:
        for phrase in (
            "pour femme",
            "night out",
            "rebel",
            "elixir",
            "intense",
            "extreme",
            "limited edition",
            "collector edition",
            "collectors edition",
        ):
            normalized_phrase = norm(phrase)

            if (
                normalized_phrase
                and normalized_phrase in product_text
                and normalized_phrase != query_variant
            ):
                return False

    for phrase in NON_PERFUME:
        normalized_phrase = norm(phrase)

        if (
            normalized_phrase in product_text
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
    return importlib.import_module(
        f"scrapers.{store}.scraper"
    )


def build_search_attempts(store: str, query: str) -> List[str]:
    """
    IMPORTANTE:
    Il vecchio main trasformava "9 PM" in 5 ricerche per OGNI store.
    Con 8 store diventavano fino a 40 ricerche HTTP per una sola ricerca.

    Ora:
      - ricerca precisa sempre
      - una sola forma compatta se serve
      - una sola forma senza marca/parole generiche per query lunghe
    """
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()

        if not value:
            return

        normalized_value = norm(value)

        if normalized_value not in {
            norm(x) for x in attempts
        }:
            attempts.append(value)

    add(raw)

    # Le family terms NON vengono lanciate automaticamente su tutti gli store.
    # Sono troppo costose e soprattutto amplificano il problema di timeout.
    # La query precisa deve essere la fonte principale.
    tokens = [
        t
        for t in normalized.split()
        if t not in IGNORED_WORDS
    ]

    # NON eliminiamo automaticamente la prima parola della query.
    # Se brand e nome sono separati dallo scraper, matches() li ricompone.
    # Eliminare il primo token qui può invece produrre ricerche troppo
    # generiche e poi risultati incoerenti.

    # Forma compatta 9 PM -> 9PM.
    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )

    if compact != normalized:
        add(compact)

    return attempts[:3]


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    module = load_scraper(store)
    attempts = build_search_attempts(store, query)

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

        # NON fermiamo lo store al primo risultato.
        #
        # Alcuni scraper (in particolare Bplatz e Sabina) possono restituire
        # solo una parte dei prodotti con la prima forma della query
        # (es. "9 PM") e altri prodotti con la forma compatta ("9PM").
        # Fermarsi al primo risultato faceva quindi sparire prodotti validi.
        #
        # Le query alternative sono al massimo 3 e vengono eseguite
        # comunque in modo sequenziale SOLO dentro questo singolo store.
        # Tutti gli store, invece, continuano a lavorare in parallelo.
        continue

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


# ============================================================
# ROOT / HEALTH
# ============================================================

@app.get("/", include_in_schema=False)
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


# ============================================================
# SEARCH
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

    # ========================================================
    # PUNTO CRITICO DEL VECCHIO MAIN
    #
    # Prima:
    #   max_workers=2
    #   8 store
    #   timeout 28 s
    #
    # Quindi gli store 1-2 partivano subito, 3-4 aspettavano,
    # 5-6 aspettavano ancora, ecc.
    #
    # Inoltre shutdown(wait=False) lasciava i thread lenti vivi
    # dopo il timeout. La ricerca successiva poteva quindi partire
    # mentre la precedente stava ancora facendo richieste.
    #
    # Ora:
    #   tutti gli store partono insieme
    #   e l'executor viene SEMPRE chiuso aspettando i worker.
    # ========================================================

    executor = ThreadPoolExecutor(
        max_workers=SEARCH_WORKERS
    )

    futures = {
        executor.submit(
            run_store,
            store,
            query,
        ): store
        for store in STORES
    }

    try:
        try:
            for future in as_completed(
                futures,
                timeout=SEARCH_TIMEOUT,
            ):
                store = futures[future]

                try:
                    all_results.extend(
                        future.result()
                    )

                except Exception as error:
                    errors[store] = (
                        f"{type(error).__name__}: {error}"
                    )
                    traceback.print_exc()

        except FuturesTimeoutError:
            # Gli store che non hanno risposto entro la finestra
            # vengono segnalati chiaramente.
            for future, store in futures.items():
                if not future.done():
                    errors[store] = (
                        "Timeout: negozio troppo lento"
                    )

    finally:
        # Non aspettare indefinitamente i worker dopo il timeout globale.
        # I risultati già completati vengono restituiti subito.
        # I future non completati vengono cancellati quando possibile.
        for future in futures:
            if not future.done():
                future.cancel()

        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )

    results = sort_by_price(
        unique_results(all_results)
    )

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }


# ============================================================
# TEST SINGOLO STORE
# ============================================================

@app.get("/test-store")
def test_store(store: str, q: str):
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
            "results": results,
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

    params = urlencode({
        "search": query,
        "limit": max(
            1,
            min(int(limit), 10),
        ),
    })

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

    output = []

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

    if len(query) >= 3:
        try:
            catalog_queries = [raw_query]

            # Una sola query principale + parole significative.
            for token in query.split():
                if (
                    len(token) >= 3
                    and token not in catalog_queries
                ):
                    catalog_queries.append(token)

            catalog_results = []
            catalog_seen = set()

            for catalog_query in catalog_queries:
                for item in fragella_search(
                    catalog_query,
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

    suggestions = []
    seen = set()

    for store in STORES:
        try:
            module = load_scraper(store)

            results = module.search(
                raw_query
            ) or []

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
            if norm(
                item.get("name", "")
            ).startswith(query)
            else 1,
            len(
                item.get("name", "")
            ),
            item.get(
                "name",
                "",
            ).lower(),
        )
    )

    suggestions = suggestions[:8]

    return {
        "query": q,
        "count": len(suggestions),
        "suggestions": suggestions,
        "source": "stores-fallback",
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

    offers = []

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

        offers.append(offer)

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
