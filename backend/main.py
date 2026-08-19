from pathlib import Path
from dataclasses import asdict, is_dataclass
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

NON_PERFUME = {
    "gift set", "set regalo", "coffret", "bundle", "deodorant", "deo spray",
    "shower gel", "body lotion", "after shave", "aftershave", "travel set",
    "discovery set", "kit", "beard", "barbe", "shampoo", "shampooing",
    "conditioner", "hair", "cheveux", "body care", "soin du corps",
    "face care", "soin du visage", "makeup", "maquillage", "skincare",
}

IGNORED_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait", "spray",
    "ml", "for", "by",
}

GENDER_ALIASES = {
    "homme": "men",
    "hommes": "men",
    "man": "men",
    "men": "men",
    "male": "men",
    "him": "men",
    "pour homme": "men",
    "femme": "women",
    "femmes": "women",
    "woman": "women",
    "women": "women",
    "female": "women",
    "her": "women",
    "pour femme": "women",
    "unisex": "unisex",
    "unisexe": "unisex",
    "mixte": "unisex",
}

FRAGRANCE_QUERY_WORDS = {
    "parfum", "parfums", "perfume", "perfumes", "fragrance", "fragrances",
    "eau", "edp", "edt", "extrait",
}

GLOBAL_SEARCH_TIMEOUT = int(os.getenv("GLOBAL_SEARCH_TIMEOUT", "55"))


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


def nested_value(value: Any) -> Any:
    return value.get("value") if isinstance(value, dict) else value


def product_field(product: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = product.get(key)
        if value not in (None, ""):
            return str(nested_value(value)).strip()
    return ""


def identity_value(product: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = nested_value(product.get(key))
        if value not in (None, ""):
            return str(value).strip()

    identity = product.get("identity")
    if isinstance(identity, dict):
        for key in keys:
            value = nested_value(identity.get(key))
            if value not in (None, ""):
                return str(value).strip()
    return ""


def product_size_ml(product: Dict[str, Any]) -> Optional[float]:
    explicit = nested_value(
        product.get("size_ml") or product.get("volume_ml") or product.get("format_ml")
    )
    if explicit not in (None, ""):
        try:
            return float(str(explicit).replace(",", "."))
        except (TypeError, ValueError):
            pass

    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        for key in ("size_ml", "volume_ml", "format_ml"):
            value = nested_value(attributes.get(key))
            if value not in (None, ""):
                try:
                    return float(str(value).replace(",", "."))
                except (TypeError, ValueError):
                    pass

    text = " ".join(str(product.get(key) or "") for key in (
        "name", "title", "product_name", "size", "format", "volume"
    ))
    match = re.search(r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl)\b", text, re.I)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
        return value * 10 if match.group(2).lower() == "cl" else value
    except ValueError:
        return None


def product_concentration(product: Dict[str, Any]) -> str:
    value = product_field(product, "concentration")
    if value:
        return norm(value)

    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        value = nested_value(attributes.get("concentration"))
        if value:
            return norm(value)

    text = norm(" ".join(str(product.get(key) or "") for key in (
        "name", "title", "product_name"
    )))
    for label, pattern in (
        ("extrait de parfum", r"\bextrait(?: de)? parfum\b"),
        ("eau de parfum", r"\beau de parfum\b|\bedp\b"),
        ("eau de toilette", r"\beau de toilette\b|\bedt\b"),
        ("eau de cologne", r"\beau de cologne\b|\bedc\b"),
        ("parfum", r"\bparfum\b"),
    ):
        if re.search(pattern, text, re.I):
            return label
    return ""


def product_availability(product: Dict[str, Any]) -> str:
    offer = product.get("offer")
    offer_value = ""
    if isinstance(offer, dict) and offer.get("availability") not in (None, ""):
        offer_value = norm(offer["availability"])

    explicit = product.get("availability")
    explicit_value = norm(explicit) if explicit not in (None, "") else ""

    if explicit_value:
        return explicit_value

    if offer_value and offer_value != "unknown":
        return offer_value

    if "available" in product:
        return "in stock" if product.get("available") is True else "out of stock"

    return offer_value or "unknown"

def product_search_text(product: Dict[str, Any]) -> str:
    """Return searchable product identity data, excluding navigation metadata."""
    values = [
        product.get("name"), product.get("title"), product.get("product_name"),
        product.get("brand"), product.get("source_brand"),
        product.get("product_line"), product.get("variant"), product.get("size"),
        product.get("size_ml"), product.get("volume"), product.get("volume_ml"),
        product.get("format"), product.get("format_ml"), product.get("pack_size"),
    ]
    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        for key, value in attributes.items():
            if key in {"size_ml", "volume_ml", "format_ml", "concentration", "gender", "packaging_type"}:
                values.append(nested_value(value))

    source = product.get("source")
    if isinstance(source, dict):
        values.extend([
            source.get("source_name"), source.get("source_brand"),
        ])

    return norm(" ".join(str(value or "") for value in values))


def product_identity_text(product: Dict[str, Any]) -> str:
    """Text used for identity matching: name + brand, not URL or diagnostics."""
    values = [
        product.get("name"), product.get("title"), product.get("product_name"),
        product.get("brand"), product.get("source_brand"),
    ]
    source = product.get("source")
    if isinstance(source, dict):
        values.extend([source.get("source_name"), source.get("source_brand")])
    return norm(" ".join(str(value or "") for value in values))


def _gender_from_text(value: Any) -> str:
    text = norm(value)
    tokens = set(text.split())
    if tokens & {"homme", "hommes", "man", "men", "male", "him"}:
        return "men"
    if tokens & {"femme", "femmes", "woman", "women", "female", "her"}:
        return "women"
    if tokens & {"unisex", "unisexe", "mixte"}:
        return "unisex"
    return ""


def product_gender(product: Dict[str, Any]) -> str:
    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        value = nested_value(attributes.get("gender"))
        if value:
            gender = _gender_from_text(value)
            if gender:
                return gender

    for key in ("gender", "name", "title", "product_name"):
        value = product.get(key)
        gender = _gender_from_text(value)
        if gender:
            return gender

    source = product.get("source")
    if isinstance(source, dict):
        gender = _gender_from_text(source.get("source_name"))
        if gender:
            return gender

    return ""


def query_gender(query: str) -> str:
    return _gender_from_text(query)


def query_is_fragrance(query: str) -> bool:
    text = norm(query)
    return bool(set(text.split()) & FRAGRANCE_QUERY_WORDS)


def product_looks_like_fragrance(product: Dict[str, Any]) -> bool:
    identity = product_identity_text(product)
    name = norm(product.get("name") or product.get("title") or product.get("product_name"))

    if any(norm(term) in identity for term in NON_PERFUME):
        return False

    category_markers = {
        "parfums homme", "parfums femme", "parfums hommes", "parfums femmes",
        "eaux de parfum", "eaux de toilette", "perfumes men", "perfumes women",
        "parfums homme pour homme", "parfums femme pour femme",
    }
    if name in category_markers:
        return False

    concentration = product_concentration(product)
    if concentration:
        return True

    fragrance_markers = (
        "eau de parfum", "eau de toilette", "eau de cologne",
        "extrait de parfum", "parfum", "perfume", "fragrance",
    )
    return any(marker in identity for marker in fragrance_markers)


def _normalise_query_tokens(query: str) -> set[str]:
    tokens = set(norm(query).split())
    normalized = set(tokens)

    for token in list(tokens):
        alias = GENDER_ALIASES.get(token)
        if alias:
            normalized.discard(token)
            normalized.add(alias)

    return normalized


def matches(product: Dict[str, Any], query: str) -> bool:
    query_normalized = norm(query)
    if not query_normalized:
        return False

    identity = product_identity_text(product)
    if not identity:
        return False

    query_tokens = _normalise_query_tokens(query)
    text_tokens = set(_normalise_query_tokens(identity))

    requested = product_size_ml({"name": query})
    if requested is not None:
        actual = product_size_ml(product)
        if actual is None or abs(actual - requested) > 0.01:
            return False

    if not product_looks_like_fragrance(product):
        return False

    wanted_gender = query_gender(query)
    if wanted_gender:
        actual_gender = product_gender(product)
        if actual_gender and actual_gender != wanted_gender and actual_gender != "unisex":
            return False
        if not actual_gender and wanted_gender not in text_tokens:
            return False

    meaningful = set(query_tokens)
    meaningful -= {
        "eau", "de", "parfum", "parfums", "perfume", "perfumes",
        "fragrance", "fragrances", "edp", "edt", "extrait", "spray",
        "ml", "cl", "for", "by", "men", "women", "unisex",
    }

    if meaningful and not meaningful.issubset(text_tokens):
        return False

    return True

def build_search_attempts(store: str, query: str) -> List[str]:
    del store
    raw = str(query or "").strip()
    normalized = norm(raw)
    if not raw or not normalized:
        return []

    attempts: List[str] = []
    seen = set()

    def add(value: str) -> None:
        key = norm(value)
        if value and key and key not in seen:
            seen.add(key)
            attempts.append(value)

    add(raw)

    tokens = [token for token in normalized.split() if token not in IGNORED_WORDS]
    if tokens:
        add(" ".join(tokens))

    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)", "", normalized
    )
    add(compact)

    return attempts

def resolve_actual_price(product: Dict[str, Any]) -> Dict[str, Any]:
    item = dict(product)
    raw_price = str(item.get("price") or "").strip()
    size = product_size_ml(item)
    unit_match = re.search(r"(?:/|per\s*)100\s*ml", raw_price, re.I)
    if unit_match and size and size > 0:
        unit = price_num(raw_price[:unit_match.start()])
        if unit is not None:
            actual = round(unit * size / 100.0, 2)
            item["price"] = f"{actual:.2f} €"
            item["price_value"] = actual
    return item


def product_identity_key(product: Dict[str, Any]) -> tuple:
    store = norm(product.get("store", ""))
    variant_id = identity_value(product, "store_variant_id", "variant_id")
    product_id = identity_value(product, "store_product_id", "product_id", "catalog_id")
    gtin = identity_value(product, "gtin", "ean", "ean13", "barcode", "upc")
    sku = identity_value(product, "sku")

    if variant_id:
        return ("variant", store, norm(variant_id))
    if product_id:
        return ("product", store, norm(product_id), norm(product.get("name", "")))
    if gtin:
        return ("gtin", store, norm(gtin))
    if sku:
        return ("sku", store, norm(sku))

    name = norm(product_field(product, "name", "title", "product_name"))
    size = product_size_ml(product)
    concentration = product_concentration(product)
    return ("fallback", store, name, size, concentration)


def unique_results(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique = []
    seen = set()
    for product in products:
        key = product_identity_key(product)
        if key not in seen:
            seen.add(key)
            unique.append(product)
    return unique


def deterministic_result_key(product: Dict[str, Any]) -> tuple:
    price = price_num(product.get("price"))
    price_key = float("inf") if price is None else round(price, 4)
    availability = product_availability(product)
    availability_rank = {"in stock": 0, "in_stock": 0, "available": 0, "out of stock": 1, "out_of_stock": 1, "unknown": 2}.get(availability, 3)
    store = norm(product.get("store", ""))
    store_rank = STORES.index(store) if store in STORES else len(STORES)
    name = norm(product_field(product, "name", "title", "product_name"))
    url = str(product.get("url") or "").strip().lower()
    return price_key, availability_rank, store_rank, name, url


def sort_by_price(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(products, key=deterministic_result_key)


def load_scraper(store: str):
    return importlib.import_module(f"scrapers.{store}.scraper")


def run_store(store: str, query: str) -> List[Dict[str, Any]]:
    module = load_scraper(store)
    search_fn = getattr(module, "search", None) or getattr(module, "scrape", None)
    if not callable(search_fn):
        raise RuntimeError(f"{store}: scraper senza funzione search()/scrape()")

    output: List[Dict[str, Any]] = []
    seen = set()

    for attempt in build_search_attempts(store, query):
        try:
            results = search_fn(attempt) or []
        except Exception as exc:
            print(f"STORE_DISCOVERY_ERROR: store={store} attempt={attempt!r} error={type(exc).__name__}: {exc}", flush=True)
            continue

        if not isinstance(results, list):
            continue

        attempt_added = 0
        for item in results:
            if not isinstance(item, dict):
                continue
            product = dict(item)
            product.setdefault("store", store)
            product = resolve_actual_price(product)
            key = product_identity_key(product)
            if key in seen:
                continue
            if matches(product, query):
                seen.add(key)
                output.append(product)
                attempt_added += 1

        if attempt_added > 0:
            break

    return output


def search_perfume(query: str) -> Dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"query": "", "count": 0, "results": [], "comparisons": [], "errors": {}}

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}
    # Limita la concorrenza per evitare che gli scraper pesanti
    # si contendano CPU/RAM/connessioni e facciano sparire
    # risultati di altri store in modo intermittente.
    max_workers = max(1, min(4, len(STORES)))
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="scent_store")
    futures = {executor.submit(run_store, store, query): store for store in STORES}

    try:
        try:
            for future in as_completed(futures, timeout=GLOBAL_SEARCH_TIMEOUT):
                store = futures[future]
                try:
                    store_results = future.result()
                    if isinstance(store_results, list):
                        all_results.extend(store_results)
                except Exception as exc:
                    errors[store] = f"{type(exc).__name__}: {exc}"
                    traceback.print_exc()
        except TimeoutError:
            for future, store in futures.items():
                if not future.done():
                    errors[store] = "Timeout: ricerca del negozio oltre il limite globale"
    finally:
        for future in futures:
            if not future.done():
                future.cancel()
        executor.shutdown(wait=False, cancel_futures=True)

    results = sort_by_price(unique_results(all_results))
    return {"query": query, "count": len(results), "results": results, "comparisons": [], "errors": errors}


def load_history() -> Dict[str, Any]:
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_history(data: Dict[str, Any]) -> None:
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
    except OSError:
        pass


def update_price_history(name: str, brand: str, best_offer: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    history_data = load_history()
    key = norm(f"{brand} {name}") or norm(name)
    history = history_data.get(key, [])
    if not isinstance(history, list):
        history = []
    if not best_offer:
        return history

    price_value = price_num(best_offer.get("price"))
    if price_value is None:
        return history

    point = {
        "date": datetime.now(timezone.utc).isoformat(),
        "value": price_value,
        "price": best_offer.get("price", ""),
        "store": best_offer.get("store", ""),
    }
    last = history[-1] if history else None
    if not last or last.get("value") != point["value"] or last.get("store") != point["store"]:
        history.append(point)
        history = history[-100:]
        history_data[key] = history
        save_history(history_data)
    return history


@app.get("/", include_in_schema=False)
def root():
    if not FRONTEND_INDEX.exists():
        raise HTTPException(status_code=500, detail="frontend/index.html non trovato")
    return FileResponse(FRONTEND_INDEX)


@app.get("/health")
def health():
    return {"status": "healthy", "stores": STORES}


@app.get("/search")
def search(q: str):
    return search_perfume(q)


@app.get("/routing")
def routing(q: str):
    return {"query": str(q or "").strip(), "stores": list(STORES)}


@app.get("/test-store")
def test_store(store: str, q: str):
    store = str(store or "").strip().lower()
    query = str(q or "").strip()
    if store not in STORES:
        raise HTTPException(status_code=400, detail="Store non valido. Disponibili: " + ", ".join(STORES))
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    try:
        results = run_store(store, query)
        return {"store": store, "query": query, "count": len(results), "results": sort_by_price(unique_results(results))}
    except Exception as error:
        traceback.print_exc()
        return {"store": store, "query": query, "count": 0, "results": [], "error": f"{type(error).__name__}: {error}"}

def _to_jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return {key: _to_jsonable(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _to_jsonable(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_to_jsonable(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _run_notino_diagnostic(query: str) -> Dict[str, Any]:
    """Run the diagnostic exposed by the currently loaded Notino scraper."""
    module = load_scraper("notino")
    diagnostic_fn = getattr(module, "diagnose", None)

    if not callable(diagnostic_fn):
        raise RuntimeError(
            "Lo scraper Notino caricato non espone diagnose(query). "
            "Verifica backend/scrapers/notino/scraper.py."
        )

    result = diagnostic_fn(str(query or "").strip())
    return _to_jsonable(result)


@app.get("/diagnose-notino")
def diagnose_notino(q: str = "Hawas for Him"):
    """Run the bounded Notino diagnostic for one query."""
    q = str(q or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    try:
        return _run_notino_diagnostic(q)
    except Exception as error:
        traceback.print_exc()
        raise HTTPException(
            status_code=500,
            detail={"type": type(error).__name__, "message": str(error)},
        )


@app.get("/diagnose-notino-compare")
def diagnose_notino_compare():
    """Compare Turathi Blue and Hawas for Him with the same diagnostic path."""
    queries = ["Turathi Blue", "Hawas for Him"]
    reports: Dict[str, Any] = {}

    for query in queries:
        try:
            reports[query] = _run_notino_diagnostic(query)
        except Exception as error:
            reports[query] = {
                "query": query,
                "error": {
                    "type": type(error).__name__,
                    "message": str(error),
                },
            }

    return {
        "queries": queries,
        "reports": reports,
    }



def fragella_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    api_key = os.getenv("FRAGELLA_API_KEY", "").strip()
    if not api_key:
        return []

    params = urlencode({"search": query, "limit": max(1, min(int(limit), 10))})
    request = Request(
        "https://api.fragella.com/api/v1/fragrances?" + params,
        headers={"x-api-key": api_key, "Accept": "application/json", "User-Agent": "ScentHunter/1.0"},
    )

    with urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if isinstance(payload, dict):
        items = payload.get("data") or payload.get("results") or payload.get("fragrances") or []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []

    output = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("Name") or item.get("name") or "").strip()
        brand = str(item.get("Brand") or item.get("brand") or "").strip()
        image = str(item.get("Image URL Transparent") or item.get("Image URL") or item.get("image") or "").strip()
        if name:
            output.append({"name": name, "brand": brand, "store": brand or "ScentHunter", "image": image, "catalog_id": item.get("_id") or item.get("id")})
    return output


def rank_catalog_suggestions(items: List[Dict[str, Any]], query: str) -> List[Dict[str, Any]]:
    query_n = norm(query)
    query_tokens = [token for token in query_n.split() if len(token) >= 2]
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
        if query_tokens and not all(token in text for token in query_tokens):
            continue
        if any(norm(phrase) in name_n for phrase in NON_PERFUME):
            continue

        key = str(item.get("catalog_id") or "").strip() or f"{brand_n}|{name_n}"
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
        ranked.append((priority, position if position >= 0 else 999, len(name_n), name_n, item))

    ranked.sort(key=lambda row: row[:4])
    return [row[4] for row in ranked[:8]]


@app.get("/suggest")
def suggest(q: str):
    raw_query = str(q or "").strip()
    if len(norm(raw_query)) < 2:
        return {"query": q, "count": 0, "suggestions": [], "source": "catalog"}
    try:
        suggestions = rank_catalog_suggestions(fragella_search(raw_query, 10), raw_query)
        return {"query": q, "count": len(suggestions), "suggestions": suggestions[:8], "source": "catalog"}
    except Exception as error:
        print("Catalog suggest error:", repr(error), flush=True)
        return {"query": q, "count": 0, "suggestions": [], "source": "catalog"}


@app.get("/autocomplete")
def autocomplete(q: str):
    return suggest(q)


@app.get("/product")
def product(name: str, brand: str = ""):
    data = search_perfume(name)
    offers = []

    for product_data in data["results"]:
        value = price_num(product_data.get("price"))
        if value is None:
            continue
        offer = dict(product_data)
        offer["price_value"] = value
        offers.append(offer)

    offers.sort(key=lambda offer: (
        offer["price_value"], norm(offer.get("store", "")),
        norm(offer.get("name", "")), str(offer.get("url", "")).lower(),
    ))

    best_offer = offers[0] if offers else None
    history = update_price_history(name=name, brand=brand, best_offer=best_offer)
    image = next((offer.get("image", "") for offer in offers if offer.get("image")), "")

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
