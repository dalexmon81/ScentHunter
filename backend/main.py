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

def normalize_query(value: str) -> str:
    value = str(value or "").strip()
    value = re.sub(r"\s+", " ", value)
    value = re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", value)
    return value.strip()

@app.get("/")
def root():
    return {"app": "ScentHunter", "status": "running"}

@app.get("/health")
def health():
    return {"status": "healthy"}

@app.get("/search")
def search_perfume(q: str):
    query = normalize_query(q)

    if not query:
        return {"query": query, "count": 0, "results": []}

    all_results = []
    errors = {}

    def run_store(store):
        try:
            try:
                module = importlib.import_module(f"backend.scrapers.{store}.scraper")
            except ModuleNotFoundError:
                module = importlib.import_module(f"scrapers.{store}.scraper")

            results = module.search(query)
            cleaned = []
            if results:
                for product in results:
                    if isinstance(product, dict):
                        product.setdefault("store", store)
                        cleaned.append(product)
            return store, cleaned, None
        except Exception as e:
            traceback.print_exc()
            return store, [], str(e)

    # I negozi vengono interrogati in parallelo:
    # un sito lento non impedisce agli altri di restituire i propri risultati.
    pool = ThreadPoolExecutor(max_workers=len(STORES))
    futures = {pool.submit(run_store, store): store for store in STORES}

    try:
        for future in as_completed(futures, timeout=15):
            store = futures[future]
            try:
                _, products, error = future.result()
                all_results.extend(products)
                if error:
                    errors[store] = error
            except Exception as e:
                errors[store] = str(e)
    except TimeoutError:
        pass
    finally:
        for future, store in futures.items():
            if not future.done():
                errors[store] = "timeout"
                future.cancel()
        pool.shutdown(wait=False, cancel_futures=True)

    return {
        "query": query,
        "count": len(all_results),
        "results": all_results,
        "errors": errors
    }
