from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


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
# LINEE DI RICERCA
# ============================================================
# Usa la linea già presente nel frontend, senza creare un secondo index.
LINE_FAMILIES: Dict[str, List[str]] = {}


def load_line_families() -> Dict[str, List[str]]:
    index_path = FRONTEND_INDEX
    if not index_path.exists():
        return {}

    try:
        text = index_path.read_text(encoding="utf-8", errors="ignore")
        match = re.search(
            r"const\s+SCENTHUNTER_AFNAN_LINES\s*=\s*(\{.*?\});",
            text,
            flags=re.S,
        )
        if not match:
            return {}

        value = json.loads(match.group(1))
        if not isinstance(value, dict):
            return {}

        return {
            norm(key): [str(item) for item in items if str(item).strip()]
            for key, items in value.items()
            if isinstance(items, list)
        }
    except Exception:
        return {}


def query_family(query: str) -> Optional[List[str]]:
    q = norm(query)
    if not q:
        return None
    for root, variants in LINE_FAMILIES.items():
        if q == root:
            return variants
    return None


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


LINE_FAMILIES = load_line_families()


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

    family = query_family(query)
    family_names = {norm(x) for x in family or []}

    for phrase in VARIANTS:
        normalized_phrase = norm(phrase)

        if (
            normalized_phrase in name
            and normalized_phrase not in query_normalized
            and not any(
                variant and variant in name
                for variant in family_names
            )
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
    """
    Una sola richiesta per negozio.
    Evita retry/varianti automatiche che moltiplicano 403/429
    e possono mandare Railway in timeout.
    """
    query = str(query or "").strip()
    return [query] if query else []


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    """
    Esegue una sola ricerca su un singolo negozio.
    Un errore del negozio viene propagato al chiamante, che lo registra
    senza interrompere gli altri negozi.
    """
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

            key = (
                str(product.get("url", "")).lower(),
                norm(product.get("name", "")),
            )

            if key in seen:
                continue

            if matches(product, query):
                seen.add(key)
                output.append(product)

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
        return {
            "query": "",
            "count": 0,
            "results": [],
            "errors": {},
        }

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    # Un solo negozio alla volta e una sola richiesta per negozio.
    # Se un negozio risponde 403/429/timeout, gli altri continuano.
    for store in STORES:
        try:
            store_results = run_store(store, query)
            all_results.extend(store_results)
        except Exception as error:
            errors[store] = f"{type(error).__name__}: {error}"
            print(
                f"SEARCH STORE ERROR | {store} | {type(error).__name__}: {error}",
                flush=True,
            )

    results = sort_by_price(unique_results(all_results))

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }


# ============================================================
# API - SUGGEST / AUTOCOMPLETE
# ============================================================

AUTOCOMPLETE_CATALOG = [
    {"brand": "Rasasi", "name": "Hawas for Him", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Ice", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Black", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Tropical", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Fire", "image": ""},
    {"brand": "Rasasi", "name": "Hawas Kobra", "image": ""},
    {"brand": "Afnan", "name": "9 PM", "image": ""},
    {"brand": "Afnan", "name": "9 PM Rebel", "image": ""},
    {"brand": "Afnan", "name": "9 PM Elixir", "image": ""},
    {"brand": "Afnan", "name": "9 PM Night Out", "image": ""},
    {"brand": "French Avenue", "name": "Liquid Brun", "image": ""},
    {"brand": "French Avenue", "name": "Liquid Brun Limited Edition", "image": ""},
]

@app.get("/suggest")
def suggest(q: str):
    query = norm(q)
    if len(query) < 2:
        return {"query": q, "count": 0, "suggestions": [], "source": "local"}

    words = query.split()
    hits = []
    for item in AUTOCOMPLETE_CATALOG:
        haystack = norm(f"{item.get('brand','')} {item.get('name','')}")
        if all(word in haystack for word in words):
            name_n = norm(item.get("name",""))
            score = 0 if name_n.startswith(query) else (1 if query in name_n else 2)
            hits.append((score, len(item.get("name","")), item))

    hits.sort(key=lambda x:(x[0],x[1],x[2].get("name","").lower()))
    suggestions=[x[2] for x in hits[:8]]
    return {"query": q, "count": len(suggestions), "suggestions": suggestions, "source": "local"}

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


# ============================================================
# API - DIAGNOSTICA SITEMAP DELOOX
# ============================================================

@app.get("/diagnose-deloox-sitemaps")
def diagnose_deloox_sitemaps(q: str = "Liquid Brun"):
    """Verifica direttamente da Railway le sitemap Deloox.

    NON modifica la ricerca normale. Ogni URL ha un timeout indipendente.
    Cerca anche la presenza della query e della categoria Liquid Brun.
    """
    query = str(q or "").strip()
    targets = [
        "https://www.deloox.com/sitemap.xml",
        "https://www.deloox.com/sitemap_category.xml",
        "https://www.deloox.com/sitemap_product.xml",
    ]

    report = {
        "query": query,
        "targets": [],
    }

    needles = [
        query.lower(),
        "/category/1132834/liquid-brun.html",
        "liquid-brun",
    ]

    for url in targets:
        started = time.perf_counter()
        entry = {
            "url": url,
            "status": None,
            "seconds": None,
            "bytes": 0,
            "content_type": "",
            "is_xml": False,
            "matches": {},
            "error": None,
        }

        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
                    "Accept-Language": "en-GB,en;q=0.9",
                },
            )
            with urlopen(request, timeout=5) as response:
                body = response.read()
                entry["status"] = getattr(response, "status", None)
                entry["content_type"] = response.headers.get("Content-Type", "")

            text = body.decode("utf-8", errors="ignore")
            entry["bytes"] = len(body)
            stripped = text.lstrip()
            entry["is_xml"] = (
                "xml" in entry["content_type"].lower()
                or stripped.startswith("<?xml")
                or stripped.startswith("<urlset")
                or stripped.startswith("<sitemapindex")
            )

            low = text.lower()
            entry["matches"] = {
                "query": needles[0] in low if needles[0] else False,
                "liquid_brun_category": needles[1] in low,
                "liquid_brun_slug": needles[2] in low,
            }

            if entry["matches"]["liquid_brun_category"]:
                idx = low.find(needles[1])
                entry["context"] = text[max(0, idx - 200): idx + 300]

        except HTTPError as exc:
            entry["status"] = exc.code
            entry["error"] = f"HTTPError: {exc.reason}"
        except (URLError, TimeoutError) as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        finally:
            entry["seconds"] = round(time.perf_counter() - started, 3)

        report["targets"].append(entry)

    return report
