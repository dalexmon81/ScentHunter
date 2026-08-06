import importlib
import os
import re
import statistics
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, TimeoutError, as_completed
from typing import Any, Dict, List
import requests
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

BASE_DIR = Path(__file__).resolve().parent

if (BASE_DIR / "static").exists():
    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

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

DEFAULT_HTML = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ScentHunter - Trova il miglior prezzo</title>
    <style>
        :root { --bg: #0f172a; --card: #1e293b; --accent: #e2e8f0; --highlight: #38bdf8; --text: #f8fafc; }
        body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; min-height: 100vh; }
        .container { width: 100%; max-width: 600px; text-align: center; margin-top: 40px; }
        h1 { font-size: 2.5rem; margin-bottom: 8px; background: linear-gradient(to right, #38bdf8, #818cf8); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
        p { color: #94a3b8; margin-bottom: 24px; }
        .search-box { position: relative; width: 100%; }
        input { width: 100%; padding: 16px 20px; font-size: 1.1rem; border-radius: 12px; border: 1px solid #334155; background: var(--card); color: white; box-sizing: border-box; outline: none; transition: border-color 0.2s; }
        input:focus { border-color: var(--highlight); }
        .suggestions { position: absolute; top: 100%; left: 0; right: 0; background: var(--card); border: 1px solid #334155; border-radius: 12px; margin-top: 8px; max-height: 300px; overflow-y: auto; z-index: 10; text-align: left; display: none; }
        .suggestion-item { padding: 12px 16px; cursor: pointer; border-bottom: 1px solid #334155; display: flex; align-items: center; gap: 12px; }
        .suggestion-item:last-child { border-bottom: none; }
        .suggestion-item:hover { background: #334155; }
        .suggestion-item img { width: 40px; height: 40px; object-fit: contain; border-radius: 6px; background: white; padding: 2px; }
        .results { margin-top: 32px; width: 100%; display: flex; flex-direction: column; gap: 12px; }
        .card { background: var(--card); border: 1px solid #334155; border-radius: 12px; padding: 16px; display: flex; align-items: center; justify-content: space-between; }
        .card-info { text-align: left; }
        .card-title { font-weight: bold; font-size: 1rem; }
        .card-store { color: #94a3b8; font-size: 0.85rem; text-transform: capitalize; }
        .card-price { font-size: 1.25rem; font-weight: bold; color: var(--highlight); }
        .card-link { background: var(--highlight); color: #0f172a; padding: 8px 16px; border-radius: 8px; text-decoration: none; font-weight: bold; font-size: 0.9rem; }
        .loader { display: none; margin: 20px auto; border: 4px solid #334155; border-top: 4px solid var(--highlight); border-radius: 50%; width: 36px; height: 36px; animation: spin 1s linear infinite; }
        @keyframes spin { 0% { transform: rotate(0deg); } 100% { transform: rotate(360deg); } }
    </style>
</head>
<body>
    <div class="container">
        <h1>ScentHunter</h1>
        <p>Cerca la tua fragranza al miglior prezzo sul web</p>
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Es. Sauvage, Bleue, Creed..." autocomplete="off">
            <div id="suggestions" class="suggestions"></div>
        </div>
        <div id="loader" class="loader"></div>
        <div id="results" class="results"></div>
    </div>

    <script>
        const input = document.getElementById('searchInput');
        const suggBox = document.getElementById('suggestions');
        const resultsBox = document.getElementById('results');
        const loader = document.getElementById('loader');

        let debounceTimer;

        input.addEventListener('input', () => {
            clearTimeout(debounceTimer);
            const query = input.value.trim();
            if (query.length < 2) {
                suggBox.style.display = 'none';
                return;
            }
            debounceTimer = setTimeout(() => fetchSuggestions(query), 300);
        });

        async function fetchSuggestions(query) {
            try {
                const res = await fetch(`/suggest?q=${encodeURIComponent(query)}`);
                const data = await res.json();
                if (data.suggestions && data.suggestions.length > 0) {
                    suggBox.innerHTML = data.suggestions.map(s => `
                        <div class="suggestion-item" onclick="triggerSearch('${s.name.replace(/'/g, "\\'")}')">
                            ${s.image ? `<img src="${s.image}" alt="">` : ''}
                            <div>
                                <div><b>${s.brand || ''}</b> ${s.name}</div>
                            </div>
                        </div>
                    `).join('');
                    suggBox.style.display = 'block';
                } else {
                    suggBox.style.display = 'none';
                }
            } catch (e) { console.error(e); }
        }

        function triggerSearch(query) {
            input.value = query;
            suggBox.style.display = 'none';
            executeSearch(query);
        }

        input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                suggBox.style.display = 'none';
                executeSearch(input.value.trim());
            }
        });

        async function executeSearch(query) {
            if (!query) return;
            resultsBox.innerHTML = '';
            loader.style.display = 'block';
            try {
                const res = await fetch(`/search?q=${encodeURIComponent(query)}`);
                const data = await res.json();
                loader.style.display = 'none';
                if (data.results && data.results.length > 0) {
                    resultsBox.innerHTML = data.results.map(r => `
                        <div class="card">
                            <div class="card-info">
                                <div class="card-title">${r.name}</div>
                                <div class="card-store">${r.store}</div>
                            </div>
                            <div style="display:flex; align-items:center; gap: 12px;">
                                <div class="card-price">€${r.price}</div>
                                ${r.link ? `<a href="${r.link}" target="_blank" class="card-link">Vedi</a>` : ''}
                            </div>
                        </div>
                    `).join('');
                } else {
                    resultsBox.innerHTML = '<p>Nessun risultato trovato.</p>';
                }
            } catch (e) {
                loader.style.display = 'none';
                resultsBox.innerHTML = '<p>Errore durante la ricerca.</p>';
            }
        }
    </script>
</body>
</html>
"""

@app.get("/")
def read_root():
    possible_paths = [
        BASE_DIR / "index.html",
        BASE_DIR / "static" / "index.html",
        BASE_DIR / "public" / "index.html",
        BASE_DIR / "frontend" / "index.html",
        BASE_DIR / "templates" / "index.html",
    ]
    
    for path in possible_paths:
        if path.is_file():
            return FileResponse(path)
            
    return HTMLResponse(DEFAULT_HTML)

def norm(text: str) -> str:
    if not text:
        return ""
    text = text.lower()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return " ".join(text.split())

def matches(product: Dict[str, Any], query: str) -> bool:
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
