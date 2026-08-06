import importlib
import os
import re
import statistics
import time
import requests
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Any, Dict, List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STORES = [
    "bplatz",
    "deloox",
    "sabina",
    "parfumcity",
    "notino",
    "ditano",
    "douglas",
    "sephora",
]

VARIANTS = ["flanker", "intense", "elixir", "parfum", "edp", "edt"]
NON_PERFUME = ["shower", "gel", "lotion", "body", "deodorant", "stick", "aftershave", "balm"]
IGNORED_WORDS = {"eau", "de", "parfum", "toilette", "edp", "edt", "for", "him", "her", "man", "woman"}

# Serve index.html alla rotta principale "/"
@app.get("/", response_class=HTMLResponse)
def read_root():
    if os.path.exists("index.html"):
        with open("index.html", "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>API ScentHunter Attive</h1><p>Trova le tue fragranze con le rotte /suggest e /search</p>"

def norm(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return " ".join(text.split())

def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Evita risultati palesemente diversi dalla ricerca,
    confrontando i token della query sia con il nome che con il brand del prodotto.
    """
    name = norm(product.get("name", ""))
    brand = norm(product.get("brand", ""))
    full_text = norm(f"{brand} {name}")
    query_normalized = norm(query)

    if not full_text:
        return False

    for phrase in VARIANTS:
        normalized_phrase = norm(phrase)
        if (
            normalized_phrase in full_text
            and normalized_phrase not in query_normalized
        ):
            return False

    for phrase in NON_PERFUME:
        normalized_phrase = norm(phrase)
        if (
            normalized_phrase in full_text
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
        token in full_text
        for token in tokens
    )

def load_scraper(store_name: str):
    return importlib.import_module(f"scrapers.{store_name}")

def build_search_attempts(query: str) -> List[str]:
    raw = str(query or "").strip()
    normalized = norm(raw)
    words = normalized.split()
    attempts = [raw]

    if len(words) > 2:
        attempts.append(" ".join(words[:2]))
    if len(words) > 1:
        attempts.append(words[0])

    unique_attempts = []
    for item in attempts:
        item_clean = item.strip()
        if item_clean and item_clean not in unique_attempts:
            unique_attempts.append(item_clean)
    return unique_attempts

def run_store(store: str, query: str) -> List[Dict[str, Any]]:
    module = load_scraper(store)
    attempts = build_search_attempts(query)

    for attempt in attempts:
        try:
            results = module.search(attempt) or []
            valid = []
            for item in results:
                if isinstance(item, dict) and matches(item, query):
                    valid.append(item)
            if valid:
                return valid
        except Exception as err:
            print(f"Error scraping {store} with query '{attempt}': {err}")
            continue

    return []

def product_image(product: Dict[str, Any]) -> str:
    return (
        product.get("image")
        or product.get("image_url")
        or product.get("img")
        or ""
    )

def unique_results(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    output = []
    for item in items:
        key = (
            norm(item.get("store", "")),
            norm(item.get("name", "")),
            item.get("price"),
        )
        if key not in seen:
            seen.add(key)
            output.append(item)
    return output

def sort_by_price(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def get_price(x):
        try:
            val = float(x.get("price", 999999))
            return val if val > 0 else 999999
        except (ValueError, TypeError):
            return 999999
    return sorted(items, key=get_price)

def fragella_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    url = f"https://api.fragella.com/v1/search?q={requests.utils.quote(query)}&limit={limit}"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return data.get("results", [])
    except Exception as e:
        print(f"Fragella API error: {e}")
    return []

def rank_catalog_suggestions(items: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    q_norm = norm(query)
    q_words = q_norm.split()
    
    scored = []
    for item in items:
        name = item.get("name", "")
        brand = item.get("brand", "")
        full = norm(f"{brand} {name}")
        
        score = 0
        if full.startswith(q_norm):
            score += 100
        elif norm(name).startswith(q_norm) or norm(brand).startswith(q_norm):
            score += 50
            
        if all(w in full for w in q_words):
            score += 20
            
        scored.append((score, item))
        
    scored.sort(key=lambda x: x[0], reverse=True)
    
    suggestions = []
    for score, item in scored:
        if score > 0 or len(q_norm) < 3:
            suggestions.append({
                "name": item.get("name"),
                "brand": item.get("brand"),
                "image": product_image(item),
                "catalog_id": item.get("catalog_id") or item.get("id"),
            })
    return suggestions

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

    # 1. CATALOGO PROFUMI
    if len(query) >= 2:
        try:
            catalog_queries = [raw_query]

            for token in query.split():
                if len(token) >= 2 and token not in catalog_queries:
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

        except Exception as error:
            print("Catalog suggest error:", repr(error))

    # 2. FALLBACK NEGOZI (con match sui prefissi delle parole)
    suggestions = []
    seen = set()

    for store in STORES:
        try:
            module = load_scraper(store)
            results = module.search(raw_query) or []

            for product in results:
                if not isinstance(product, dict):
                    continue

                name = str(product.get("name") or "").strip()
                brand = str(product.get("brand") or "").strip()
                if not name:
                    continue

                haystack = norm(f"{brand} {name}")
                words = query.split()

                haystack_words = haystack.split()
                if not all(
                    any(hw.startswith(w) for hw in haystack_words)
                    for w in words
                ):
                    continue

                if any(norm(phrase) in norm(name) for phrase in NON_PERFUME):
                    continue

                key = (norm(brand), norm(name))
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
            pass

    suggestions.sort(
        key=lambda item: (
            0 if norm(item.get("name", "")).startswith(query) else 1,
            0 if norm(item.get("brand", "")).startswith(query) else 1,
            len(item.get("name", "")),
        )
    )

    return {
        "query": q,
        "count": len(suggestions[:8]),
        "suggestions": suggestions[:8],
        "source": "stores-fallback",
    }

@app.get("/search")
def search_perfume(q: str):
    query = str(q or "").strip()

    if not query:
        return {"query": "", "count": 0, "results": [], "errors": {}}

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    executor = ThreadPoolExecutor(max_workers=4)
    futures = {
        executor.submit(run_store, store, query): store
        for store in STORES
    }

    try:
        for future in as_completed(futures, timeout=25):
            store = futures[future]
            try:
                all_results.extend(future.result())
            except Exception as error:
                errors[store] = f"{type(error).__name__}: {error}"
    except TimeoutError:
        pass
    finally:
        for future, store in futures.items():
            if not future.done():
                errors[store] = "Timeout: negozio troppo lento"
        executor.shutdown(wait=False, cancel_futures=True)

    results = sort_by_price(unique_results(all_results))

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
