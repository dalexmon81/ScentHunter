from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import importlib
import traceback
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

app = FastAPI(
    title="ScentHunter API",
    version="0.1.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
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


@app.get("/")
def root():
    return {
        "app": "ScentHunter",
        "status": "running"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


def price_to_number(product):
    for key in ("price", "price_text", "current_price", "sale_price", "amount"):
        value = product.get(key)
        if value not in (None, ""):
            break
    else:
        return float("inf")

    if isinstance(value, (int, float)):
        return float(value)

    s = str(value).strip()
    matches = re.findall(r"\d+(?:[.,]\d{1,2})?", s)
    if not matches:
        return float("inf")

    raw = next((m for m in matches if "," in m or "." in m), matches[0])

    try:
        return float(raw.replace(",", "."))
    except ValueError:
        return float("inf")


def _run_store(store, query):
    """
    Esegue un singolo scraper.
    Se la query originale non produce risultati, prova anche
    la variante compatta (es. 9 PM -> 9PM).
    """
    try:
        module = importlib.import_module(
            f"scrapers.{store}.scraper"
        )

        results = module.search(query)

        if not results:
            compact_variant = re.sub(
                r"(?<=\d)\s+(?=[A-Za-z])|(?<=[A-Za-z])\s+(?=\d)",
                "",
                query
            )

            if compact_variant != query:
                results = module.search(compact_variant)

        if not results:
            return store, [], None

        cleaned = []

        for product in results:
            if isinstance(product, dict):
                product.setdefault("store", store)
                cleaned.append(product)

        return store, cleaned, None

    except Exception as e:
        traceback.print_exc()
        return store, [], str(e)


@app.get("/search")
def search_perfume(q: str):
    # Conserva la query originale.
    query = re.sub(r"\s+", " ", str(q or "")).strip()

    if not query:
        return {
            "query": query,
            "count": 0,
            "results": []
        }

    all_results = []
    errors = {}

    # IMPORTANTE:
    # tutti gli scraper vengono eseguiti IN PARALLELO.
    # Un negozio lento/non raggiungibile non blocca gli altri.
    with ThreadPoolExecutor(max_workers=len(STORES)) as pool:
        futures = {
            pool.submit(_run_store, store, query): store
            for store in STORES
        }

        for future in as_completed(futures):
            store, results, error = future.result()

            if error:
                errors[store] = error

            if results:
                all_results.extend(results)

    # Ordine globale: meno caro -> più caro.
    all_results.sort(key=price_to_number)

    return {
        "query": query,
        "count": len(all_results),
        "results": all_results,
        "errors": errors
    }
