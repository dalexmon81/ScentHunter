from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import importlib
import json
import os
import re
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

app = FastAPI(title="ScentHunter API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://.*",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

TITLE = "ScentHunter"
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
HISTORY_PATH = os.path.join(BASE_DIR, "pricehistory.json")
FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
AUTOCOMPLETE_CACHE_PATH = os.path.join(BASE_DIR, "autocomplete_catalog.json")
AUTOCOMPLETE_TTL_SECONDS = 60 * 60 * 12
AUTOCOMPLETE_MAX_WORKERS = 8
AUTOCOMPLETE_FETCH_LIMIT = 18
AUTOCOMPLETE_RESULT_LIMIT = 10
AUTOCOMPLETE_MIN_QUERY = 2
AUTOCOMPLETE_TIMEOUT_PER_STORE = 2.2

VARIANTS = [
    "pour femme",
    "night out",
    "rebel",
    "elixir",
    "intense",
    "extreme",
    "limited edition",
    "collector edition",
    "collectors edition",
]

NONPERFUME = [
    "gift set",
    "set regalo",
    "coffret",
    "bundle",
    "deodorant",
    "deo spray",
    "deodorante",
    "shower gel",
    "body lotion",
    "after shave",
    "aftershave",
    "travel set",
    "discovery set",
    "kit",
    "soap",
    "sabon",
    "gel doccia",
    "bath",
    "hair mist",
    "body mist",
    "deo",
    "stick",
    "refill bottle",
    "refillable case",
]

IGNORED_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray", "ml", "for", "by"
}

AUTOCOMPLETE_STATE: Dict[str, Any] = {
    "items": [],
    "built_at": None,
    "expires_at": 0.0,
    "building": False,
    "last_error": None,
}
AUTOCOMPLETE_LOCK = threading.Lock()


def norm(value: Any) -> str:
    value = str(value or "").lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def price_num(value: Any) -> Optional[float]:
    match = re.search(r"(\d{1,5}[\.,]\d{1,2})", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def product_image(product: Dict[str, Any]) -> str:
    return product.get("image") or product.get("image_url") or product.get("thumbnail") or ""


def contains_nonperfume(text: str) -> bool:
    normalized = norm(text)
    return any(norm(phrase) in normalized for phrase in NONPERFUME)


def matches_product(product: Dict[str, Any], query: str) -> bool:
    name = norm(product.get("name"))
    query_normalized = norm(query)
    if not name:
        return False

    for phrase in VARIANTS:
        normalized_phrase = norm(phrase)
        if normalized_phrase in name and normalized_phrase not in query_normalized:
            return False

    for phrase in NONPERFUME:
        normalized_phrase = norm(phrase)
        if normalized_phrase in name and normalized_phrase not in query_normalized:
            return False

    tokens = [token for token in query_normalized.split() if token not in IGNORED_WORDS]
    if not tokens:
        return False

    return all(token in name for token in tokens)


def autocomplete_matches_text(query: str, brand: str, name: str) -> bool:
    query_normalized = norm(query)
    if len(query_normalized) < AUTOCOMPLETE_MIN_QUERY:
        return False

    haystack = norm(f"{brand} {name}")
    if not haystack:
        return False

    tokens = [token for token in query_normalized.split() if token]
    if not tokens:
        return False

    if not all(token in haystack for token in tokens):
        return False

    compact_query = query_normalized.replace(" ", "")
    compact_haystack = haystack.replace(" ", "")
    if compact_query and compact_query in compact_haystack:
        return True

    return query_normalized in haystack or any(haystack.startswith(token) for token in tokens)


def autocomplete_score(item: Dict[str, Any], query: str) -> Tuple[int, int, int, str]:
    brand = item.get("brand", "")
    name = item.get("name", "")
    haystack = norm(f"{brand} {name}")
    query_normalized = norm(query)
    compact_haystack = haystack.replace(" ", "")
    compact_query = query_normalized.replace(" ", "")

    starts = 0 if haystack.startswith(query_normalized) or compact_haystack.startswith(compact_query) else 1
    contains = 0 if query_normalized in haystack or compact_query in compact_haystack else 1
    length_bias = len(name or "")
    return (starts, contains, length_bias, (brand + " " + name).lower())


def load_scraper(store: str):
    return importlib.import_module(f"scrapers.{store}.scraper")


def build_search_attempts(store: str, query: str) -> List[str]:
    attempts = [query]
    normalized_query = norm(query)
    compact = re.sub(r"\s+", "", normalized_query)

    if compact and compact not in attempts:
        attempts.append(compact)

    if store == "bplatz":
        for token in normalized_query.split():
            if token and token not in attempts:
                attempts.append(token)

    return attempts


def run_store(store: str, query: str) -> List[Dict[str, Any]]:
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
            product.setdefault("store", store)

            key = (str(product.get("url", "")).lower(), norm(product.get("name", "")))
            if key in seen:
                continue
            seen.add(key)

            if matches_product(product, query):
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
    def key(product: Dict[str, Any]):
        value = price_num(product.get("price"))
        return value if value is not None else float("inf")

    return sorted(products, key=key)


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


def update_price_history(name: str, brand: str, best_offer: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    history_data = load_history()
    key = norm(f"{brand} {name}" or norm(name))
    history = history_data.get(key, [])

    if not isinstance(history, list):
        history = []

    if not best_offer:
        return history

    point = {
        "date": datetime.now(timezone.utc).isoformat(),
        "value": best_offer.get("price_value"),
        "price": best_offer.get("price", ""),
        "store": best_offer.get("store", ""),
    }

    last = history[-1] if history else None
    changed = not last or last.get("value") != point["value"] or last.get("store") != point["store"]

    if changed:
        history.append(point)
        history = history[-100:]
        history_data[key] = history
        save_history(history_data)

    return history


def autocomplete_item_key(brand: str, name: str) -> str:
    return norm(f"{brand} {name}")


def build_catalog_entry(product: Dict[str, Any], store: str) -> Optional[Dict[str, Any]]:
    name = str(product.get("name") or product.get("title") or product.get("product_name") or "").strip()
    brand = str(product.get("brand") or "").strip()

    if not name:
        return None

    full_text = f"{brand} {name}".strip()
    if contains_nonperfume(full_text):
        return None

    return {
        "name": name,
        "brand": brand,
        "image": product_image(product),
        "store": store,
        "key": autocomplete_item_key(brand, name),
    }


def save_autocomplete_cache(items: List[Dict[str, Any]], built_at: str) -> None:
    payload = {"built_at": built_at, "items": items}
    try:
        with open(AUTOCOMPLETE_CACHE_PATH, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
    except OSError:
        pass


def load_autocomplete_cache() -> None:
    try:
        with open(AUTOCOMPLETE_CACHE_PATH, "r", encoding="utf-8") as file:
            payload = json.load(file)

        items = payload.get("items", [])
        built_at = payload.get("built_at")

        if isinstance(items, list):
            with AUTOCOMPLETE_LOCK:
                AUTOCOMPLETE_STATE["items"] = items
                AUTOCOMPLETE_STATE["built_at"] = built_at
                AUTOCOMPLETE_STATE["expires_at"] = time.time() + AUTOCOMPLETE_TTL_SECONDS
    except Exception:
        pass


def refresh_store_catalog(store: str) -> List[Dict[str, Any]]:
    module = load_scraper(store)
    collected: List[Dict[str, Any]] = []
    seen = set()

    letters = list("abcdefghijklmnopqrstuvwxyz")
    hot_queries = [
        "a", "e", "h", "ha", "m", "n", "o", "s", "t", "u", "v", "y",
        "for", "pour", "man", "woman", "intense", "elixir"
    ]
    probes = letters + hot_queries

    for probe in probes:
        try:
            results = module.search(probe) or []
        except Exception:
            continue

        for product in results[:AUTOCOMPLETE_FETCH_LIMIT]:
            if not isinstance(product, dict):
                continue

            entry = build_catalog_entry(product, store)
            if not entry:
                continue

            key = entry["key"]
            if key in seen:
                continue

            seen.add(key)
            collected.append(entry)

    return collected


def rebuild_autocomplete_catalog_sync() -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    merged: Dict[str, Dict[str, Any]] = {}

    with ThreadPoolExecutor(max_workers=AUTOCOMPLETE_MAX_WORKERS) as executor:
        futures = {executor.submit(refresh_store_catalog, store): store for store in STORES}

        for future in as_completed(futures, timeout=max(10, len(STORES) * AUTOCOMPLETE_TIMEOUT_PER_STORE)):
            try:
                entries = future.result(timeout=AUTOCOMPLETE_TIMEOUT_PER_STORE)
            except Exception:
                traceback.print_exc()
                continue

            for entry in entries:
                key = entry["key"]
                existing = merged.get(key)

                if not existing:
                    merged[key] = entry
                    continue

                if not existing.get("image") and entry.get("image"):
                    existing["image"] = entry["image"]

                if not existing.get("brand") and entry.get("brand"):
                    existing["brand"] = entry["brand"]

    items = sorted(
        merged.values(),
        key=lambda item: ((item.get("brand") or "").lower(), (item.get("name") or "").lower())
    )

    with AUTOCOMPLETE_LOCK:
        AUTOCOMPLETE_STATE["items"] = items
        AUTOCOMPLETE_STATE["built_at"] = now_iso
        AUTOCOMPLETE_STATE["expires_at"] = time.time() + AUTOCOMPLETE_TTL_SECONDS
        AUTOCOMPLETE_STATE["building"] = False
        AUTOCOMPLETE_STATE["last_error"] = None

    save_autocomplete_cache(items, now_iso)


def rebuild_autocomplete_catalog_background() -> None:
    try:
        rebuild_autocomplete_catalog_sync()
    except Exception as error:
        traceback.print_exc()
        with AUTOCOMPLETE_LOCK:
            AUTOCOMPLETE_STATE["building"] = False
            AUTOCOMPLETE_STATE["last_error"] = f"{type(error).__name__}: {error}"


def ensure_autocomplete_catalog() -> None:
    should_start = False

    with AUTOCOMPLETE_LOCK:
        is_empty = not AUTOCOMPLETE_STATE["items"]
        expired = time.time() > float(AUTOCOMPLETE_STATE.get("expires_at") or 0)
        building = bool(AUTOCOMPLETE_STATE["building"])

        if (is_empty or expired) and not building:
            AUTOCOMPLETE_STATE["building"] = True
            should_start = True

    if should_start:
        threading.Thread(target=rebuild_autocomplete_catalog_background, daemon=True).start()


def autocomplete_from_catalog(query: str) -> List[Dict[str, Any]]:
    ensure_autocomplete_catalog()
    with AUTOCOMPLETE_LOCK:
        items = list(AUTOCOMPLETE_STATE["items"])

    matches = [
        item for item in items
        if autocomplete_matches_text(query, item.get("brand", ""), item.get("name", ""))
    ]
    matches.sort(key=lambda item: autocomplete_score(item, query))
    return matches[:AUTOCOMPLETE_RESULT_LIMIT]


def autocomplete_live_fallback(query: str) -> List[Dict[str, Any]]:
    suggestions: List[Dict[str, Any]] = []
    seen = set()

    def fetch_store(store: str) -> List[Dict[str, Any]]:
        module = load_scraper(store)
        attempts = []

        raw = str(query or "").strip()
        normalized = norm(query)
        compact = normalized.replace(" ", "")

        for attempt in [raw, normalized, compact]:
            if attempt and attempt not in attempts:
                attempts.append(attempt)

        rows: List[Dict[str, Any]] = []

        for attempt in attempts:
            results = module.search(attempt) or []
            for product in results[:AUTOCOMPLETE_FETCH_LIMIT]:
                if not isinstance(product, dict):
                    continue
                entry = build_catalog_entry(product, store)
                if entry:
                    rows.append(entry)

        return rows

    with ThreadPoolExecutor(max_workers=min(4, len(STORES))) as executor:
        futures = {executor.submit(fetch_store, store): store for store in STORES}

        for future in as_completed(futures, timeout=4):
            try:
                rows = future.result(timeout=AUTOCOMPLETE_TIMEOUT_PER_STORE)
            except Exception:
                continue

            for entry in rows:
                if not autocomplete_matches_text(query, entry.get("brand", ""), entry.get("name", "")):
                    continue

                key = entry["key"]
                if key in seen:
                    continue

                seen.add(key)
                suggestions.append(entry)

    suggestions.sort(key=lambda item: autocomplete_score(item, query))
    return suggestions[:AUTOCOMPLETE_RESULT_LIMIT]


load_autocomplete_cache()
ensure_autocomplete_catalog()


@app.get("/", include_in_schema=False)
def root():
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=500, detail="frontend/index.html non trovato")
    return FileResponse(FRONTEND_INDEX)


@app.get("/health")
def health():
    return {"status": "healthy", "stores": STORES, "title": TITLE}


@app.get("/search")
def search_perfume(q: str):
    query = (q or "").strip()
    if not query:
        return {"query": "", "count": 0, "results": [], "errors": {}}

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    for store in STORES:
        try:
            results = run_store(store, query)
            all_results.extend(results)
        except Exception as error:
            errors[store] = f"{type(error).__name__}: {error}"
            traceback.print_exc()

    results = unique_results(all_results)
    results = sort_by_price(results)

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }


@app.get("/suggest")
def suggest(q: str):
    query = norm(q)

    if len(query) < AUTOCOMPLETE_MIN_QUERY:
        return {
            "query": q,
            "count": 0,
            "suggestions": [],
            "source": "catalog",
            "catalog_ready": False,
        }

    suggestions = autocomplete_from_catalog(q)
    source = "catalog"
    catalog_ready = bool(suggestions)

    if not suggestions:
        suggestions = autocomplete_live_fallback(q)
        source = "live"

    payload = [
        {
            "name": item.get("name", ""),
            "brand": item.get("brand", ""),
            "image": item.get("image", ""),
            "store": item.get("store", ""),
        }
        for item in suggestions
    ]

    return {
        "query": q,
        "count": len(payload),
        "suggestions": payload,
        "source": source,
        "catalog_ready": catalog_ready,
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
    history = update_price_history(name=name, brand=brand, best_offer=best_offer)
    image = next((offer.get("image") for offer in offers if offer.get("image")), "")

    return {
        "name": name,
        "brand": brand,
        "image": image,
        "lowest_price": best_offer.get("price") if best_offer else None,
        "best_offer": best_offer,
        "offers": offers,
        "history": history,
        "errors": data["errors"],
        "message": "" if offers else "Nessuna offerta disponibile al momento",
    }
