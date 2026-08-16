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
    """Poche query mirate: precisa prima, poi più corta."""
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()
        if value and norm(value) not in [norm(x) for x in attempts]:
            attempts.append(value)

    add(raw)

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

        if output:
            break

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
        return {"query": "", "count": 0, "results": [], "errors": {}}

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    # NON 8 insieme: su Render Free abbiamo osservato exit 137.
    # Due worker riducono nettamente RAM e connessioni simultanee.
    executor = ThreadPoolExecutor(max_workers=2)
    futures = {
        executor.submit(run_store, store, query): store
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

    results = sort_by_price(unique_results(all_results))

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


@app.get("/test-deloox-diagnostic")
def test_deloox_diagnostic(q: str):
    """Diagnostic-only Deloox endpoint; normal search endpoints unchanged."""
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")
    try:
        module = load_scraper("deloox")
        if not hasattr(module, "diagnose_search"):
            raise HTTPException(
                status_code=500,
                detail="Deloox scraper senza diagnose_search()"
            )
        return module.diagnose_search(query)
    except HTTPException:
        raise
    except Exception as error:
        traceback.print_exc()
        return {"query": query, "error": f"{type(error).__name__}: {error}"}


@app.get("/test-deloox-step1")
def test_deloox_step1(q: str = "Liquid Brun"):
    """One-request Deloox diagnostic. Deliberately does NOT load the scraper."""
    import time as _time
    import requests as _requests

    query = str(q or "").strip()
    url = "https://www.deloox.com/category/1075750/mens-perfume.html"
    started = _time.perf_counter()

    try:
        r = _requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                              "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=8,
        )
        elapsed = round(_time.perf_counter() - started, 3)
        body = r.text or ""
        q_norm = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
        body_norm = re.sub(r"[^a-z0-9]+", " ", body.lower())
        tokens = [x for x in q_norm.split() if len(x) > 1]

        return {
            "step": 1,
            "query": query,
            "url": url,
            "seconds": elapsed,
            "status": r.status_code,
            "bytes": len(r.content),
            "query_tokens_seen": {
                token: token in body_norm for token in tokens
            },
            "message": "ONE REQUEST ONLY — no scraper, no pagination, no sitemap, no product validation",
        }
    except Exception as error:
        return {
            "step": 1,
            "query": query,
            "url": url,
            "seconds": round(_time.perf_counter() - started, 3),
            "error": f"{type(error).__name__}: {error}",
            "message": "ONE REQUEST ONLY — failure occurred before any scraper logic",
        }


@app.get("/test-deloox-step2")
def test_deloox_step2(q: str = "Liquid Brun"):
    """Step 2: one category request + URL extraction only. No product requests."""
    import time as _time
    import requests as _requests
    from bs4 import BeautifulSoup as _BeautifulSoup
    from urllib.parse import urljoin as _urljoin

    query = str(q or "").strip()
    url = "https://www.deloox.com/category/1075750/mens-perfume.html"
    started = _time.perf_counter()

    try:
        r = _requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                              "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=8,
        )
        html = r.text or ""
        soup = _BeautifulSoup(html, "html.parser")

        all_links = []
        product_links = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = _urljoin(url, a.get("href", "").strip())
            if href in seen:
                continue
            seen.add(href)
            all_links.append(href)

            path = href.lower()
            if "/product/" in path:
                product_links.append(href)

        q_norm = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
        tokens = [x for x in q_norm.split() if len(x) > 1]

        # Show only links whose visible anchor text or href contains query tokens.
        matching_links = []
        for a in soup.find_all("a", href=True):
            text = " ".join(a.stripped_strings)
            combined = (text + " " + a.get("href", "")).lower()
            if tokens and all(t in combined for t in tokens):
                matching_links.append({
                    "text": text[:180],
                    "url": _urljoin(url, a.get("href", "").strip())
                })

        return {
            "step": 2,
            "query": query,
            "url": url,
            "seconds": round(_time.perf_counter() - started, 3),
            "status": r.status_code,
            "bytes": len(r.content),
            "all_links": len(all_links),
            "product_links": len(product_links),
            "sample_product_urls": product_links[:30],
            "matching_query_links": matching_links[:30],
            "message": "ONE REQUEST ONLY — URL extraction only; ZERO product pages opened",
        }

    except Exception as error:
        return {
            "step": 2,
            "query": query,
            "url": url,
            "seconds": round(_time.perf_counter() - started, 3),
            "error": f"{type(error).__name__}: {error}",
            "message": "Failure during URL extraction; ZERO product pages opened",
        }


@app.get("/test-deloox-step3")
def test_deloox_step3(q: str = "Liquid Brun"):
    """Step 3: category pagination only; no product pages opened."""
    import time as _time
    import requests as _requests
    from bs4 import BeautifulSoup as _BeautifulSoup
    from urllib.parse import urljoin as _urljoin

    query = str(q or "").strip()
    base = "https://www.deloox.com/category/1075750/mens-perfume.html"
    q_norm = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
    tokens = [x for x in q_norm.split() if len(x) > 1]
    session = _requests.Session()
    pages = []
    started_all = _time.perf_counter()

    try:
        for page_no in range(1, 13):
            url = base if page_no == 1 else base + "?page=" + str(page_no)
            started = _time.perf_counter()
            try:
                r = session.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                                      "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
                        "Accept-Language": "en-GB,en;q=0.9",
                    },
                    timeout=8,
                )
                html = r.text or ""
                soup = _BeautifulSoup(html, "html.parser")
                product_urls = []
                matching = []
                seen = set()

                for a in soup.find_all("a", href=True):
                    href = _urljoin(url, a.get("href", "").strip())
                    if "/product/" not in href.lower() or href in seen:
                        continue
                    seen.add(href)
                    product_urls.append(href)
                    text = " ".join(a.stripped_strings)
                    combined = (text + " " + href).lower()
                    if tokens and all(t in combined for t in tokens):
                        matching.append({"text": text[:160], "url": href})

                pages.append({
                    "page": page_no,
                    "url": url,
                    "seconds": round(_time.perf_counter() - started, 3),
                    "status": r.status_code,
                    "bytes": len(r.content),
                    "product_links": len(product_urls),
                    "query_matches": matching[:20],
                    "sample_product_urls": product_urls[:8],
                })

                # Stop on a page that is clearly not a real category page.
                if r.status_code >= 400 or not product_urls:
                    break

            except Exception as exc:
                pages.append({
                    "page": page_no,
                    "url": url,
                    "seconds": round(_time.perf_counter() - started, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                })
                break
    finally:
        session.close()

    return {
        "step": 3,
        "query": query,
        "pages_tested": len(pages),
        "total_seconds": round(_time.perf_counter() - started_all, 3),
        "pages": pages,
        "message": "CATEGORY PAGINATION ONLY — ZERO product pages opened",
    }


@app.get("/test-deloox-step4")
def test_deloox_step4(q: str = "Liquid Brun"):
    """Step 4: discover Deloox category structure; no product pages opened."""
    import time as _time
    import requests as _requests
    from bs4 import BeautifulSoup as _BeautifulSoup
    from urllib.parse import urljoin as _urljoin, urlparse as _urlparse

    query = str(q or "").strip()
    q_norm = re.sub(r"[^a-z0-9]+", " ", query.lower()).strip()
    tokens = [x for x in q_norm.split() if len(x) > 1]

    started = _time.perf_counter()
    homepage = "https://www.deloox.com/"
    session = _requests.Session()

    try:
        r = session.get(
            homepage,
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
                              "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
                "Accept-Language": "en-GB,en;q=0.9",
            },
            timeout=10,
        )
        soup = _BeautifulSoup(r.text or "", "html.parser")

        categories = []
        seen = set()

        for a in soup.find_all("a", href=True):
            href = _urljoin(homepage, a.get("href", "").strip())
            parsed = _urlparse(href)
            path = parsed.path.lower()
            if "/category/" not in path or href in seen:
                continue
            seen.add(href)

            text = " ".join(a.stripped_strings).strip()
            combined = (text + " " + href).lower()

            token_hits = [t for t in tokens if t in combined]
            perfume_hits = [
                w for w in (
                    "perfume", "parfum", "fragrance", "fragrances",
                    "mens", "men", "women", "woman", "unisex",
                    "niche", "limited", "new", "exclusive"
                )
                if w in combined
            ]

            score = len(token_hits) * 100 + len(perfume_hits)

            categories.append({
                "text": text[:160],
                "url": href,
                "score": score,
                "query_token_hits": token_hits,
                "category_keywords": perfume_hits[:12],
            })

        categories.sort(
            key=lambda x: (x["score"], bool(x["text"]), len(x["text"])),
            reverse=True
        )

        return {
            "step": 4,
            "query": query,
            "seconds": round(_time.perf_counter() - started, 3),
            "status": r.status_code,
            "bytes": len(r.content),
            "category_links_found": len(categories),
            "top_categories": categories[:80],
            "message": (
                "CATEGORY DISCOVERY ONLY — ONE REQUEST, ZERO product pages opened. "
                "This step tells us which Deloox category family should be searched next."
            ),
        }

    except Exception as exc:
        return {
            "step": 4,
            "query": query,
            "seconds": round(_time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "message": "Category discovery failed; ZERO product pages opened",
        }
    finally:
        session.close()

