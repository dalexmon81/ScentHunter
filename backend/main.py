from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
from html import unescape
import os
import re
import traceback
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


app = FastAPI(title="ScentHunter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

VARIANTS = {
    "pour femme", "night out", "rebel", "elixir", "intense",
    "extreme", "limited edition", "collector edition", "collector's edition",
}

NON_PERFUME = {
    "gift set", "set regalo", "coffret", "bundle", "deodorant",
    "deo spray", "shower gel", "body lotion", "after shave",
    "aftershave", "travel set", "discovery set", "kit",
}

IGNORED_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "ml", "for", "by",
}


def norm(value: Any) -> str:
    value = str(value or "").lower().strip()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def price_num(value: Any) -> Optional[float]:
    match = re.search(r"(\d{1,5}(?:[.,]\d{1,2})?)", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def product_image(product: Dict[str, Any]) -> str:
    return (
        product.get("image")
        or product.get("image_url")
        or product.get("thumbnail")
        or ""
    )


def _product_size_ml(product: Dict[str, Any]) -> Optional[float]:
    text = " ".join(
        str(product.get(key) or "")
        for key in ("name", "title", "product_name", "size_ml", "size")
    )
    match = re.search(r"\b(\d{1,4}(?:[.,]\d+)?)\s*ml\b", text, re.I)
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def _price_from_structured_html(html: str) -> Optional[float]:
    """
    Cerca il PREZZO REALE di vendita nella pagina prodotto.
    Preferisce dati strutturati (JSON-LD/meta) rispetto al prezzo per 100 ml.
    Funziona trasversalmente sui negozi che espongono il prezzo standard web.
    """
    html = unescape(html or "")

    # 1) JSON-LD: Product -> offers -> price.
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
                    n = price_num(offers.get(key))
                    if n is not None:
                        yield n
            elif isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        for key in ("price", "lowPrice"):
                            n = price_num(offer.get(key))
                            if n is not None:
                                yield n
            # Alcuni negozi mettono direttamente price nel Product.
            if str(value.get("@type", "")).lower() == "product":
                n = price_num(value.get("price"))
                if n is not None:
                    yield n
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
            # Il primo prezzo Product/Offer è quello più affidabile; non usiamo
            # i prezzi aggregati di comparatori esterni presenti nella pagina.
            return prices[0]

    # 2) Meta tag comuni di Shopify/WooCommerce/OpenGraph.
    patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            n = price_num(match.group(1))
            if n is not None:
                return n

    return None


def resolve_actual_price(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizza il prezzo mostrato da ScentHunter al prezzo realmente pagabile.

    Problema risolto: alcuni scraper possono intercettare il prezzo unitario
    (es. 26,66 €/100 ml) invece del prezzo della confezione (es. 39,99 €).
    Prima prova la pagina prodotto; solo se non è disponibile usa il calcolo
    da prezzo unitario quando il campo lo dichiara esplicitamente.
    """
    item = dict(product)
    raw_price = str(item.get("price") or "").strip()
    size = _product_size_ml(item)

    # Se la pagina è disponibile, il prezzo strutturato è la fonte primaria.
    url = str(item.get("url") or "").strip()
    if url and size and abs(size - 100.0) > 0.01:
        try:
            request = Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "Mozilla/5.0 (compatible; ScentHunter/1.0)",
                },
            )
            with urlopen(request, timeout=4) as response:
                html = response.read().decode("utf-8", errors="ignore")
            actual = _price_from_structured_html(html)
            if actual is not None:
                item["price"] = f"{actual:.2f} €"
                item["price_value"] = actual
                return item
        except Exception:
            pass

    # Fallback sicuro: converti SOLO quando il testo dichiara esplicitamente
    # che il valore è un prezzo unitario per 100 ml.
    unit_match = re.search(r"(?:/|per\s*)100\s*ml", raw_price, re.I)
    if unit_match and size and size > 0:
        unit = price_num(raw_price[:unit_match.start()])
        if unit is not None:
            actual = round(unit * size / 100.0, 2)
            item["price"] = f"{actual:.2f} €"
            item["price_value"] = actual

    return item


def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Match generale del prodotto.

    IMPORTANTE: non scartiamo automaticamente le varianti (Limited Edition,
    Elixir, Rebel, ecc.). La UI deve poterle mostrare come prodotti distinti.
    Filtriamo invece i veri non-profumi (gift set, deodoranti, kit...).
    """
    name_tokens = set(norm(product.get("name", "")).split())
    query_all_tokens = set(norm(query).split())

    if not name_tokens or not query_all_tokens:
        return False

    for phrase in NON_PERFUME:
        phrase_tokens = set(norm(phrase).split())
        if (
            phrase_tokens
            and phrase_tokens.issubset(name_tokens)
            and not phrase_tokens.issubset(query_all_tokens)
        ):
            return False

    query_tokens = {
        token
        for token in query_all_tokens
        if token not in IGNORED_WORDS
    }

    if not query_tokens:
        query_tokens = query_all_tokens

    return bool(query_tokens) and query_tokens.issubset(name_tokens)


def load_scraper(store: str):
    return importlib.import_module(f"scrapers.{store}.scraper")


def build_search_attempts(store: str, query: str) -> List[str]:
    attempts = [query]
    normalized_query = norm(query)

    if store == "bplatz":
        # Bplatz can index the product under the exact perfume name, while
        # its visible title may include the brand/house. Keep the exact query
        # first, then use progressively broader searches.
        compact = re.sub(
            r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
            "",
            normalized_query,
        )
        if compact and compact not in attempts:
            attempts.append(compact)

        # Search the significant tokens separately. This is important when
        # Shopify's product handle does not contain every word of the query.
        for token in normalized_query.split():
            if token and token not in attempts:
                attempts.append(token)

    elif store == "deloox":
        # Deloox's catalogue/search layer may require the house/brand to
        # resolve a product page. The original query remains first so normal
        # searches are unchanged; the enriched attempt is only a fallback.
        if normalized_query:
            enriched = f"french avenue {normalized_query}"
            if enriched not in attempts:
                attempts.append(enriched)

        for token in normalized_query.split():
            if token and token not in attempts:
                attempts.append(token)

    return attempts


def run_store(store: str, query: str) -> List[Dict[str, Any]]:
    module = load_scraper(store)
    search_fn = getattr(module, "search", None)

    if not callable(search_fn):
        raise RuntimeError(f"{store}: scraper senza funzione search()")

    attempts = build_search_attempts(store, query)
    output: List[Dict[str, Any]] = []
    seen = set()

    for attempt in attempts:
        results = search_fn(attempt) or []

        for item in results:
            if not isinstance(item, dict):
                continue

            product = dict(item)
            product.setdefault("store", store)
            product = resolve_actual_price(product)

            key = (
                str(product.get("url", "")).lower(),
                norm(product.get("name", "")),
            )

            if key in seen:
                continue

            seen.add(key)

            if matches(product, query):
                output.append(product)
                continue

            # Some store pages prepend/translate the house name or format
            # the product title differently. Do not weaken the global matcher;
            # only retry the two problematic stores with a token-based check
            # against the product URL/title. This cannot admit gift sets,
            # testers, deodorants, etc.
            if store in {"bplatz", "deloox"}:
                name_text = norm(
                    " ".join(
                        str(product.get(key) or "")
                        for key in ("name", "title", "product_name", "url")
                    )
                )
                query_tokens = {
                    token for token in norm(query).split()
                    if token not in IGNORED_WORDS
                }

                if (
                    query_tokens
                    and query_tokens.issubset(set(name_text.split()))
                    and not any(
                        set(norm(phrase).split()).issubset(set(name_text.split()))
                        and not set(norm(phrase).split()).issubset(
                            set(norm(query).split())
                        )
                        for phrase in NON_PERFUME
                    )
                ):
                    output.append(product)

    return output


def unique_results(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def sort_by_price(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(product):
        value = price_num(product.get("price"))
        return float("inf") if value is None else value

    return sorted(products, key=key)


def search_perfume(query: str) -> Dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"query": query, "count": 0, "results": [], "comparisons": [], "errors": {}}

    results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    executor = ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="scent-store",
    )
    future_to_store = {
        executor.submit(run_store, store, query): store
        for store in STORES
    }

    done, not_done = wait(future_to_store, timeout=30)

    for future in done:
        store = future_to_store[future]
        try:
            results.extend(future.result() or [])
        except Exception as exc:
            errors[store] = str(exc) or exc.__class__.__name__

    for future in not_done:
        store = future_to_store[future]
        errors[store] = "timeout"
        future.cancel()

    executor.shutdown(wait=False, cancel_futures=True)

    results = sort_by_price(unique_results(results))

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "comparisons": [],
        "errors": errors,
    }


@app.get("/search")
def search(q: str):
    return search_perfume(q)


@app.get("/test-store")
def test_store(store: str, q: str):
    """Endpoint diagnostico per testare un solo scraper."""
    store = str(store or "").strip().lower()
    query = str(q or "").strip()

    if store not in STORES:
        raise HTTPException(
            status_code=400,
            detail=f"Store non valido. Disponibili: {', '.join(STORES)}",
        )
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

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


def load_history() -> Dict[str, Any]:
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def save_history(data: Dict[str, Any]) -> None:
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except OSError:
        pass


def update_price_history(
    name: str,
    brand: str,
    best_offer: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    history_data = load_history()
    key = norm(f"{brand} {name}") or norm(name)
    history = history_data.get(key, [])

    if not isinstance(history, list):
        history = []

    if not best_offer:
        return history

    point = {
        "date": datetime.now(timezone.utc).isoformat(),
        "value": best_offer["price_value"],
        "price": best_offer.get("price", ""),
        "store": best_offer.get("store", ""),
    }

    last = history[-1] if history else None

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
    return {"status": "healthy", "stores": STORES}


def fragella_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
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
        payload = json.loads(response.read().decode("utf-8"))

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

        name = str(item.get("Name") or item.get("name") or "").strip()
        brand = str(item.get("Brand") or item.get("brand") or "").strip()
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
            "catalog_id": item.get("_id") or item.get("id"),
        })

    return output


def rank_catalog_suggestions(
    items: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    query_n = norm(query)
    tokens = [token for token in query_n.split() if len(token) >= 2]
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

        if any(norm(phrase) in name_n for phrase in NON_PERFUME):
            continue

        key = (
            str(item.get("catalog_id") or "").strip()
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

        ranked.append((priority, position, len(name_n), name_n, item))

    ranked.sort(key=lambda row: row[:4])
    return [row[4] for row in ranked[:8]]


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
            print("Catalog suggest error:", repr(error))
        except Exception:
            traceback.print_exc()

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
                    brand = str(product.get("brand") or "").strip()
                    haystack = norm(f"{brand} {name}")
                    words = [word for word in query.split() if word]

                    if not all(word in haystack for word in words):
                        continue

                    if any(
                        norm(phrase) in normalized_name
                        for phrase in NON_PERFUME
                    ):
                        continue

                    key = (norm(brand), normalized_name)

                    if key in seen:
                        continue

                    seen.add(key)

                    suggestions.append({
                        "name": name,
                        "store": product.get("store", store),
                        "brand": brand,
                        "image": product_image(product),
                    })

        except Exception:
            traceback.print_exc()

    suggestions.sort(
        key=lambda item: (
            0 if norm(item.get("name", "")).startswith(query) else 1,
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


@app.get("/autocomplete")
def autocomplete(q: str):
    return suggest(q)


@app.get("/product")
def product(name: str, brand: str = ""):
    data = search_perfume(name)
    offers: List[Dict[str, Any]] = []

    for product_data in data["results"]:
        value = price_num(product_data.get("price"))

        if value is None:
            continue

        offer = dict(product_data)
        offer["price_value"] = value
        offer["image"] = product_image(offer)
        offers.append(offer)

    offers.sort(key=lambda offer: offer["price_value"])
    best_offer = offers[0] if offers else None

    history = update_price_history(
        name=name,
        brand=brand,
        best_offer=best_offer,
    )

    image = next(
        (offer["image"] for offer in offers if offer.get("image")),
        "",
    )

    lowest_price = best_offer.get("price") if best_offer else None

    return {
        "name": name,
        "brand": brand,
        "image": image,
        "lowest_price": lowest_price,
        "best_offer": best_offer,
        "offers": offers,
        "history": history,
        "errors": data["errors"],
        "message": "" if offers else "Nessuna offerta disponibile al momento",
    }
