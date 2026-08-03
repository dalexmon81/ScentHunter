from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import importlib
import traceback
import re

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

    for store in STORES:
        try:
            try:
                module = importlib.import_module(f"backend.scrapers.{store}.scraper")
            except ModuleNotFoundError:
                module = importlib.import_module(f"scrapers.{store}.scraper")

            results = module.search(query)

            if results:
                for product in results:
                    if isinstance(product, dict):
                        product.setdefault("store", store)
                        all_results.append(product)

        except Exception as e:
            errors[store] = str(e)
            traceback.print_exc()

    return {
        "query": query,
        "count": len(all_results),
        "results": all_results,
        "errors": errors
    }
