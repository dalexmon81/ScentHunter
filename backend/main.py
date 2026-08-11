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

app = FastAPI(title="ScentHunter API", version="1.0.0")

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
FRONTEND_INDEX = Path(__file__).resolve().parent.parent / "frontend" / "index.html"
CATALOG_FILENAME = "scenthunter_catalog.json"

VARIANT_MARKERS = {
    "pour femme", "pour homme", "femme", "homme",
    "flame", "energy", "parfum", "night", "night out",
    "rebel", "elixir", "intense", "extreme",
    "limited", "limited edition", "collector",
    "collector edition", "collector's edition",
    "special edition", "anniversary", "ice",
    "blanc", "noir", "nude", "rose", "blue", "red",
    "black", "white", "gold", "silver", "coral",
    "fantasy", "sport", "absolu", "le parfum",
    "the parfum", "most wanted",
}

VARIANTS = VARIANT_MARKERS

NON_PERFUME = {
    "gift set", "set regalo", "coffret", "bundle", "travel set",
    "discovery set", "kit", "deodorant", "deodorante", "deodorants",
    "deodorantes", "déodorant", "deo", "deo spray", "deo stick",
    "deostick", "deodorant stick", "deodorant spray",
    "deodorant roll on", "antiperspirant", "antitranspirant",
    "anti transpirant", "anti-transpirant", "shampoo", "shampo",
    "conditioner", "hair conditioner", "hair care", "hair",
    "shower gel", "showergel", "gel douche", "gel doccia",
    "doccia gel", "duschgel", "dusch gel", "duschbad", "dusch bad",
    "shower", "body wash", "body gel", "bath", "bath gel", "bath oil",
    "bagnoschiuma", "bagno schiuma", "douche", "gel da bagno",
    "body lotion", "body cream", "body creme", "body butter",
    "body moisturizer", "body moisturiser", "body balm", "body mist",
    "hair mist", "face mist", "fragrance mist", "body splash",
    "hand cream", "hand creme", "hand lotion", "face cream",
    "face creme", "face lotion", "face wash", "facial cream",
    "facial lotion", "cream", "creme", "crème", "crema",
    "creme hydratante", "lotion", "lozione", "locion", "lotion corps",
    "moisturizer", "moisturiser", "emulsion", "émulsion", "emulsione",
    "serum", "siero", "balsam", "balm", "baume", "körperlotion",
    "körper lotion", "körpercreme", "körper creme", "gesichtscreme",
    "gesicht creme", "handcreme", "haarshampoo", "body oil", "oil",
    "huile", "olio", "fragrance oil", "perfume oil", "essential oil",
    "huile essentielle", "körperöl", "körper öl", "soap", "savon",
    "sapone", "seife", "shaving", "shave", "after shave", "aftershave",
    "beard", "barba", "rasage", "razor", "roll on", "roll-on", "rasier",
    "candle", "diffuser", "room spray", "home fragrance", "fabric spray",
    "scrub", "cleanser", "mask", "toothpaste", "toothbrush", "detergent",
    "powder", "talc",
}

SET_PRODUCTS = {
    "gift set", "set regalo", "coffret", "bundle", "travel set",
    "discovery set", "kit",
}

IGNORED_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt", "extrait",
    "spray", "ml", "for", "by",
}


# ============================================================
# NORMALIZZAZIONE
# ============================================================

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


def _contains_term(text: str, phrase: str) -> bool:
    text_n = norm(text)
    phrase_n = norm(phrase)
    if not text_n or not phrase_n:
        return False
    return bool(
        re.search(
            r"(?<![a-z0-9])" + re.escape(phrase_n) + r"(?![a-z0-9])",
            text_n,
        )
    )


def _word_tokens(value: Any) -> List[str]:
    return re.findall(
        r"[A-Za-zÀ-ÿ0-9]+(?:['’][A-Za-zÀ-ÿ0-9]+)?",
        str(value or ""),
    )


# ============================================================
# CATALOGO MASTER
# ============================================================

CATALOG_ALIASES: Dict[str, str] = {}
CATALOG_BRANDS: Dict[str, str] = {}
CATALOG_PRODUCTS: List[Dict[str, Any]] = []


def _catalog_paths() -> List[Path]:
    base = Path(BASE_DIR).resolve()
    candidates = [
        base / CATALOG_FILENAME,
        base.parent / CATALOG_FILENAME,
        Path.cwd() / CATALOG_FILENAME,
    ]
    out = []
    seen = set()
    for path in candidates:
        if str(path) not in seen:
            seen.add(str(path))
            out.append(path)
    return out


def _load_catalog() -> None:
    global CATALOG_PRODUCTS, CATALOG_ALIASES, CATALOG_BRANDS

    payload = None
    for path in _catalog_paths():
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
            break
        except (OSError, ValueError, TypeError):
            continue

    if not isinstance(payload, dict):
        return

    products = payload.get("products", [])
    if not isinstance(products, list):
        return

    CATALOG_PRODUCTS = [x for x in products if isinstance(x, dict)]

    for item in CATALOG_PRODUCTS:
        brand = str(item.get("brand") or "").strip()
        canonical = str(item.get("name") or "").strip()
        if not canonical:
            continue

        candidates = [canonical]
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            candidates.extend(str(x or "").strip() for x in aliases)

        for candidate in candidates:
            if not candidate:
                continue
            key = norm(candidate)
            CATALOG_ALIASES[key] = canonical
            if brand:
                CATALOG_ALIASES[norm(f"{brand} {candidate}")] = canonical
                CATALOG_BRANDS[key] = brand
                CATALOG_BRANDS[norm(f"{brand} {candidate}")] = brand

        if brand:
            CATALOG_BRANDS[norm(canonical)] = brand


_load_catalog()


def _catalog_brand_candidates(query: str) -> List[str]:
    tokens = [
        x for x in norm(query).split()
        if x not in IGNORED_WORDS
    ]
    if not tokens:
        return []

    candidates = [tokens]
    core = [
        token for token in tokens
        if not any(token == part for marker in VARIANT_MARKERS for part in norm(marker).split())
    ]
    if core and core != tokens:
        candidates.append(core)

    brands = []
    seen = set()

    for wanted in candidates:
        for item in CATALOG_PRODUCTS:
            brand = str(item.get("brand") or "").strip()
            name = str(item.get("name") or "").strip()
            if not brand or not name:
                continue

            haystack = norm(f"{brand} {name}")
            if all(token in haystack for token in wanted):
                key = norm(brand)
                if key not in seen:
                    seen.add(key)
                    brands.append(brand)

    return brands[:4]


def _catalog_family_products(query: str) -> List[Dict[str, Any]]:
    q = norm(query)
    if not q:
        return []

    if re.search(r"(?:^|\s)9\s*pm(?:\s|$)", q):
        family = "9 pm"
    elif re.search(r"(?:^|\s)9\s*am(?:\s|$)", q):
        family = "9 am"
    elif re.search(r"\ble\s+beau\b", q):
        family = "le beau"
    else:
        return []

    out = []
    seen = set()

    for item in CATALOG_PRODUCTS:
        name = norm(item.get("name"))
        brand = norm(item.get("brand"))
        if not name:
            continue

        if family == "9 pm":
            ok = bool(re.search(r"(?:^|\s)9\s*pm(?:\s|$)", name))
        elif family == "9 am":
            ok = bool(re.search(r"(?:^|\s)9\s*am(?:\s|$)", name))
        else:
            ok = "le beau" in name

        if not ok:
            continue

        key = f"{brand}|{name}"
        if key not in seen:
            seen.add(key)
            out.append(item)

    return out


def canonical_product_brand(product: Dict[str, Any]) -> str:
    raw_name = str(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
        or ""
    ).strip()
    brand = str(product.get("brand") or "").strip()

    return (
        CATALOG_BRANDS.get(norm(raw_name))
        or CATALOG_BRANDS.get(norm(f"{brand} {raw_name}"))
        or brand
    ).strip()


def _move_gender_to_end(name: str) -> str:
    gender_re = re.compile(
        r"\b(uomo|donna|men|women|man|woman|homme|femme)\b",
        re.I,
    )
    match = gender_re.search(name)
    if not match:
        return name

    gender_map = {
        "uomo": "Uomo", "donna": "Donna",
        "men": "Uomo", "man": "Uomo",
        "women": "Donna", "woman": "Donna",
        "homme": "Uomo", "femme": "Donna",
    }

    gender = gender_map[match.group(1).lower()]
    cleaned = gender_re.sub(" ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return f"{cleaned} {gender}".strip()


def canonical_product_name(
    product: Dict[str, Any],
    family_query: str = "",
) -> str:
    raw_name = str(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
        or ""
    ).strip()
    brand = canonical_product_brand(product)

    if not raw_name:
        return ""

    canonical = (
        CATALOG_ALIASES.get(norm(raw_name))
        or CATALOG_ALIASES.get(norm(f"{brand} {raw_name}"))
    )
    name = canonical or raw_name

    if brand:
        name = re.sub(
            rf"^\s*{re.escape(brand)}\s*[-–—:]?\s*",
            "",
            name,
            flags=re.I,
        ).strip()

    name = _move_gender_to_end(name)

    collapsed = []
    for word in name.split():
        if collapsed and norm(collapsed[-1]) == norm(word):
            continue
        collapsed.append(word)

    return re.sub(
        r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)",
        " ",
        " ".join(collapsed),
    ).strip()


def normalize_product(
    product: Dict[str, Any],
    family_query: str = "",
) -> Dict[str, Any]:
    item = dict(product)
    item["brand"] = canonical_product_brand(item)
    item["name"] = canonical_product_name(item, family_query)

    brand = str(item.get("brand") or "").strip()
    name = str(item.get("name") or "").strip()
    item["display_name"] = f"{brand} - {name}" if brand else name
    return item


# ============================================================
# FILTRI
# ============================================================

def _is_set_product(product: Dict[str, Any]) -> bool:
    fields = (
        "name", "title", "product_name",
        "category", "type", "product_type",
    )
    text = norm(" ".join(str(product.get(x) or "") for x in fields))
    return any(_contains_term(text, x) for x in SET_PRODUCTS)


def _product_search_text(product: Dict[str, Any]) -> str:
    fields = (
        "name", "title", "product_name", "description",
        "category", "type", "product_type",
        "sub_category", "subcategory",
    )
    return norm(" ".join(str(product.get(x) or "") for x in fields))


def is_non_perfume(product: Dict[str, Any]) -> bool:
    if _is_set_product(product):
        return False

    text = _product_search_text(product)
    if not text:
        return True

    return any(_contains_term(text, x) for x in NON_PERFUME)


def _family_key(query: str) -> Optional[str]:
    q = norm(query)
    if re.search(r"(?:^|\s)9\s*pm(?:\s|$)", q):
        return "9 pm"
    if re.search(r"(?:^|\s)9\s*am(?:\s|$)", q):
        return "9 am"
    if re.search(r"\ble\s+beau\b", q):
        return "le beau"
    return None


def _query_variant(query: str) -> Optional[str]:
    q = norm(query)
    for marker in VARIANT_MARKERS:
        marker_n = norm(marker)
        if marker_n and _contains_term(q, marker_n):
            return marker_n
    return None


def matches(product: Dict[str, Any], query: str) -> bool:
    item = normalize_product(product, query)
    name = norm(item.get("name", ""))
    q = norm(query)

    if not name or is_non_perfume(item):
        return False

    family = _family_key(query)

    # IMPORTANTISSIMO:
    # Una ricerca di famiglia deve accettare tutte le varianti che lo
    # scraper trova. Non chiediamo che il titolo sia identico alla query.
    if family == "9 pm":
        return bool(re.search(r"(?:^|\s)9\s*pm(?:\s|$)", name))

    if family == "9 am":
        return bool(re.search(r"(?:^|\s)9\s*am(?:\s|$)", name))

    if family == "le beau":
        return "le beau" in name

    tokens = [
        token for token in q.split()
        if token not in IGNORED_WORDS
    ]

    if not tokens or not all(token in name for token in tokens):
        return False

    requested_variant = _query_variant(query)
    if requested_variant:
        for marker in VARIANT_MARKERS:
            marker_n = norm(marker)
            if (
                marker_n
                and _contains_term(name, marker_n)
                and marker_n != requested_variant
            ):
                return False

    return True


# ============================================================
# SCRAPER
# ============================================================

def load_scraper(store: str):
    return importlib.import_module(f"scrapers.{store}.scraper")


def build_search_attempts(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
) -> List[str]:
    """
    Regola generale:
    - query originale sempre;
    - poche query aggiuntive;
    - nessun nome di profumo hard-coded;
    - per una famiglia, usa le forme trovate nel catalogo;
    - massimo 5 tentativi per store.
    """
    raw = str(query or "").strip()
    normalized = norm(raw)

    attempts = []
    seen = set()

    def add(value: Any):
        value = str(value or "").strip()
        key = norm(value)
        if key and key not in seen:
            seen.add(key)
            attempts.append(value)

    add(raw)

    family = _family_key(raw)

    if family:
        # Prima query originale.
        # Poi le forme presenti nel catalogo. Se il catalogo è incompleto,
        # aggiungiamo anche il brand scoperto dal catalogo senza trasformarlo
        # in un filtro dei risultati.
        family_items = _catalog_family_products(raw)

        # Massimo due forme aggiuntive, scelte dal catalogo.
        # La query originale resta sempre la prima.
        for item in family_items[:2]:
            brand = str(item.get("brand") or "").strip()
            name = str(item.get("name") or "").strip()
            if brand and name:
                add(f"{brand} {name}")
            elif name:
                add(name)

        return attempts[:3]

    tokens = [
        x for x in normalized.split()
        if x not in IGNORED_WORDS
    ]

    if len(tokens) >= 2:
        add(" ".join(tokens[1:]))

    if len(tokens) >= 3:
        add(" ".join(tokens[-2:]))

    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )
    if compact != normalized:
        add(compact)

    for brand in catalog_hints or []:
        add(brand)

    return attempts[:5]


def run_store(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    Esegue UNO store.

    Non interrompe la ricerca dopo il primo risultato:
    una query successiva può trovare una variante che la prima non ha trovato.
    """
    module = load_scraper(store)

    attempts = build_search_attempts(
        store,
        query,
        catalog_hints,
    )

    output = []
    seen = set()

    for attempt in attempts:
        try:
            results = module.search(attempt) or []
        except Exception as error:
            print(f"[{store}] errore query {attempt!r}: {error}")
            continue

        for item in results:
            if not isinstance(item, dict):
                continue

            product = normalize_product(
                {
                    **item,
                    "store": item.get("store") or store,
                },
                query,
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

    return output


# ============================================================
# DEDUPLICAZIONE / ORDINAMENTO
# ============================================================

def unique_results(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique = []
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


def sort_by_name(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        products,
        key=lambda product: (
            norm(
                product.get("display_name")
                or f"{product.get('brand', '')} {product.get('name', '')}"
            ),
            norm(product.get("store", "")),
            str(product.get("url", "")).lower(),
        ),
    )


def sort_by_price(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        products,
        key=lambda product: (
            price_num(product.get("price"))
            if price_num(product.get("price")) is not None
            else float("inf")
        ),
    )


# ============================================================
# PRICE HISTORY
# ============================================================

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


# ============================================================
# API ROOT / HEALTH
# ============================================================

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
    return {
        "status": "healthy",
        "stores": STORES,
        "catalog_loaded": bool(CATALOG_PRODUCTS),
        "catalog_products": len(CATALOG_PRODUCTS),
    }


# ============================================================
# API SEARCH
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

    catalog_hints = _catalog_brand_candidates(query)

    # Tutti gli store partono subito. Il numero di query per store è stato
    # ridotto sopra per evitare il moltiplicarsi delle richieste.
    max_workers = min(8, len(STORES))

    executor = ThreadPoolExecutor(max_workers=max_workers)

    futures = {
        executor.submit(
            run_store,
            store,
            query,
            catalog_hints,
        ): store
        for store in STORES
    }

    # 45s è il limite globale: gli store rapidi restituiscono subito,
    # quelli che non rispondono non bloccano la pagina indefinitamente.
    search_timeout = 45

    try:
        for future in as_completed(
            futures,
            timeout=search_timeout,
        ):
            store = futures[future]

            try:
                all_results.extend(future.result())
            except Exception as error:
                errors[store] = f"{type(error).__name__}: {error}"
                traceback.print_exc()

    except TimeoutError:
        # Conserviamo tutto ciò che è arrivato.
        # Gli store ancora in esecuzione vengono marcati come timeout.
        for future, store in futures.items():
            if not future.done():
                errors.setdefault(
                    store,
                    "Timeout: negozio troppo lento",
                )

    finally:
        # NON aspettiamo indefinitamente i thread lenti.
        # I thread già terminati hanno già consegnato i loro risultati.
        for future, store in futures.items():
            if future.done():
                continue

            if future.cancel():
                errors.setdefault(
                    store,
                    "Ricerca annullata dopo il timeout",
                )
            else:
                errors.setdefault(
                    store,
                    "Timeout: ricerca non completata",
                )

        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )

    normalized_results = [
        normalize_product(product, query)
        for product in all_results
    ]

    results = sort_by_name(
        unique_results(normalized_results)
    )

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }


# ============================================================
# TEST SINGOLO STORE
# ============================================================

@app.get("/test-store")
def test_store(store: str, q: str):
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
        results = run_store(
            store,
            query,
            _catalog_brand_candidates(query),
        )

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
# SUGGEST / FRAGELLA
# ============================================================

def fragella_search(
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
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

    output = []

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
            "catalog_id": item.get("_id") or item.get("id"),
        })

    return output


def rank_catalog_suggestions(
    items: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:
    query_n = norm(query)
    tokens = [
        token for token in query_n.split()
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

        if any(_contains_term(name_n, phrase) for phrase in NON_PERFUME):
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

        ranked.append((
            priority,
            position,
            len(name_n),
            name_n,
            item,
        ))

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

            catalog_results = []
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

    # Fallback negozi: SOLO autocomplete.
    suggestions = []
    seen = set()

    for store in STORES:
        try:
            module = load_scraper(store)

            for attempt in (raw_query, query):
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

                    brand = str(product.get("brand") or "").strip()
                    normalized_name = norm(name)
                    haystack = norm(f"{brand} {name}")

                    if not all(
                        word in haystack
                        for word in query.split()
                        if word
                    ):
                        continue

                    if any(
                        _contains_term(normalized_name, phrase)
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


# ============================================================
# PRODUCT
# ============================================================

@app.get("/product")
def product(
    name: str,
    brand: str = "",
):
    data = search_perfume(name)

    offers = []

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
