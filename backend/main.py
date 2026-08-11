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

# Il catalogo è SOLO una sorgente di nomi/brand per aiutare le query.
# NON viene mai usato per decidere quali risultati di un negozio sono validi.
CATALOG_FILENAME = "scenthunter_catalog.json"

VARIANTS = {
    "pour femme",
    "pour homme",
    "femme",
    "homme",
    "night out",
    "rebel",
    "elixir",
    "intense",
    "extreme",
    "limited",
    "limited edition",
    "collector",
    "collector edition",
    "collector's edition",
    "special edition",
    "anniversary",
    "ice",
    "flame",
    "energy",
    "sport",
    "parfum",
    "most wanted",
}

FAMILY_SEARCH_TERMS = {
    "9 pm": [
        "9 PM",
        "9PM",
        "9 PM Pour Femme",
        "9PM Pour Femme",
        "9 PM Elixir",
        "9PM Elixir",
        "9 PM Night Out",
        "9PM Night Out",
        "9 PM Rebel",
        "9PM Rebel",
    ],
    "9 am": [
        "9 AM",
        "9AM",
        "9 AM Pour Femme",
        "9AM Pour Femme",
        "9 AM Dive",
        "9AM Dive",
    ],
    "le beau": [
        "Le Beau",
        "Le Beau Le Parfum",
        "Le Beau Paradise Garden",
        "Le Beau Narcisse",
    ],
}

NON_PERFUME = {
    "gift set",
    "set regalo",
    "coffret",
    "bundle",
    "deodorant",
    "deodorante",
    "deodorants",
    "deodorantes",
    "deo",
    "deo spray",
    "deo stick",
    "deostick",
    "deodorant stick",
    "deodorant spray",
    "deodorant roll on",
    "antiperspirant",
    "antitranspirant",
    "shower gel",
    "showergel",
    "gel douche",
    "gel doccia",
    "duschgel",
    "dusch gel",
    "duschbad",
    "body lotion",
    "body cream",
    "body creme",
    "body butter",
    "body milk",
    "body mist",
    "hair mist",
    "face mist",
    "fragrance mist",
    "hand cream",
    "hand creme",
    "hand lotion",
    "face cream",
    "face creme",
    "face lotion",
    "cream",
    "creme",
    "crème",
    "crema",
    "lotion",
    "lozione",
    "moisturizer",
    "moisturiser",
    "emulsion",
    "emulsione",
    "serum",
    "siero",
    "balm",
    "baume",
    "shampoo",
    "conditioner",
    "hair care",
    "body wash",
    "bagnoschiuma",
    "soap",
    "savon",
    "sapone",
    "seife",
    "shaving",
    "shave",
    "after shave",
    "aftershave",
    "beard",
    "barba",
    "razor",
    "roll on",
    "roll-on",
    "candle",
    "diffuser",
    "room spray",
    "home fragrance",
    "fabric spray",
    "scrub",
    "cleanser",
    "mask",
    "toothpaste",
    "toothbrush",
    "detergent",
    "powder",
    "talc",
    "body oil",
    "oil",
    "huile",
    "olio",
    "fragrance oil",
    "perfume oil",
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
# NORMALIZZAZIONE
# ============================================================

def norm(value: Any) -> str:
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

    return re.sub(r"\s+", " ", value).strip()


def price_num(value: Any) -> Optional[float]:
    match = re.search(
        r"(\d{1,5}(?:[.,]\d{1,2})?)",
        str(value or ""),
    )

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
            r"(?<![a-z0-9])"
            + re.escape(phrase_n)
            + r"(?![a-z0-9])",
            text_n,
        )
    )


def _is_non_perfume_name(name: str) -> bool:
    return any(
        _contains_term(name, phrase)
        for phrase in NON_PERFUME
        if norm(phrase)
    )


def _query_tokens(query: str) -> List[str]:
    return [
        token
        for token in norm(query).split()
        if token not in IGNORED_WORDS
    ]


def family_key(query: str) -> Optional[str]:
    q = norm(query)

    if re.search(r"(?:^|\s)9\s*pm(?:\s|$)", q):
        return "9 pm"

    if re.search(r"(?:^|\s)9\s*am(?:\s|$)", q):
        return "9 am"

    if re.search(r"\ble\s+beau\b", q):
        return "le beau"

    return None


# ============================================================
# CATALOGO LOCALE
# ============================================================

CATALOG_PRODUCTS: List[Dict[str, Any]] = []
CATALOG_BRANDS: Dict[str, str] = {}


def _catalog_paths() -> List[Path]:
    base = Path(BASE_DIR).resolve()

    candidates = [
        base / CATALOG_FILENAME,
        base.parent / CATALOG_FILENAME,
        Path.cwd() / CATALOG_FILENAME,
    ]

    unique = []
    seen = set()

    for candidate in candidates:
        key = str(candidate)

        if key not in seen:
            seen.add(key)
            unique.append(candidate)

    return unique


def _load_catalog() -> None:
    global CATALOG_PRODUCTS, CATALOG_BRANDS

    payload = None

    for path in _catalog_paths():
        try:
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            break
        except (OSError, ValueError, TypeError):
            continue

    if not isinstance(payload, dict):
        return

    products = payload.get("products", [])

    if not isinstance(products, list):
        return

    CATALOG_PRODUCTS = [
        item
        for item in products
        if isinstance(item, dict)
    ]

    brands = {}

    for item in CATALOG_PRODUCTS:
        brand = str(item.get("brand") or "").strip()
        name = str(item.get("name") or "").strip()

        if not brand or not name:
            continue

        brands[norm(name)] = brand
        brands[norm(f"{brand} {name}")] = brand

        aliases = item.get("aliases")

        if isinstance(aliases, list):
            for alias in aliases:
                alias = str(alias or "").strip()

                if alias:
                    brands[norm(alias)] = brand
                    brands[norm(f"{brand} {alias}")] = brand

    CATALOG_BRANDS = brands


_load_catalog()


def catalog_brand_candidates(query: str) -> List[str]:
    tokens = _query_tokens(query)

    if not tokens:
        return []

    brands = []
    seen = set()

    for item in CATALOG_PRODUCTS:
        brand = str(item.get("brand") or "").strip()
        name = str(item.get("name") or "").strip()

        if not brand or not name:
            continue

        text = norm(f"{brand} {name}")

        if all(token in text for token in tokens):
            key = norm(brand)

            if key not in seen:
                seen.add(key)
                brands.append(brand)

        if len(brands) >= 4:
            break

    return brands


def catalog_family_names(query: str) -> List[str]:
    family = family_key(query)

    if not family:
        return []

    output = []
    seen = set()

    for item in CATALOG_PRODUCTS:
        name = str(item.get("name") or "").strip()

        if not name:
            continue

        name_n = norm(name)

        if family == "9 pm":
            ok = bool(
                re.search(
                    r"(?:^|\s)9\s*pm(?:\s|$)",
                    name_n,
                )
            )
        elif family == "9 am":
            ok = bool(
                re.search(
                    r"(?:^|\s)9\s*am(?:\s|$)",
                    name_n,
                )
            )
        else:
            ok = "le beau" in name_n

        if not ok:
            continue

        key = name_n

        if key not in seen:
            seen.add(key)
            output.append(name)

    return output


# ============================================================
# NORMALIZZAZIONE PRODOTTI
# ============================================================

def canonical_brand(product: Dict[str, Any]) -> str:
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


def normalize_product(
    product: Dict[str, Any],
) -> Dict[str, Any]:

    item = dict(product)

    raw_name = str(
        item.get("name")
        or item.get("title")
        or item.get("product_name")
        or ""
    ).strip()

    brand = canonical_brand(item)

    item["brand"] = brand
    item["name"] = raw_name
    item["display_name"] = (
        f"{brand} - {raw_name}"
        if brand
        else raw_name
    )

    if "image" not in item:
        item["image"] = product_image(item)

    return item


# ============================================================
# FILTRO RISULTATI
# ============================================================

def matches(
    product: Dict[str, Any],
    query: str,
) -> bool:

    item = normalize_product(product)

    name = norm(item.get("name", ""))
    query_n = norm(query)

    if not name:
        return False

    if _is_non_perfume_name(name):
        return False

    family = family_key(query)

    # Per una ricerca di famiglia, il nome deve appartenere alla famiglia.
    # Non richiediamo il nome esatto: così 9 PM Pour Femme, Night Out,
    # Rebel, Elixir ecc. possono comparire quando il negozio li restituisce.
    if family == "9 pm":
        return bool(
            re.search(
                r"(?:^|\s)9\s*pm(?:\s|$)",
                name,
            )
        )

    if family == "9 am":
        return bool(
            re.search(
                r"(?:^|\s)9\s*am(?:\s|$)",
                name,
            )
        )

    if family == "le beau":
        return "le beau" in name

    tokens = _query_tokens(query)

    if not tokens:
        return False

    # Tutti i termini significativi della query devono essere nel nome.
    if not all(token in name for token in tokens):
        return False

    # Se l'utente ha chiesto una variante precisa, non mostriamo
    # una variante diversa.
    query_variant = None

    for phrase in VARIANTS:
        phrase_n = norm(phrase)

        if phrase_n and _contains_term(query_n, phrase_n):
            query_variant = phrase_n
            break

    if query_variant:
        for phrase in VARIANTS:
            phrase_n = norm(phrase)

            if (
                phrase_n
                and _contains_term(name, phrase_n)
                and phrase_n != query_variant
            ):
                return False

    return True


# ============================================================
# SCRAPER
# ============================================================

def load_scraper(store: str):
    return importlib.import_module(
        f"scrapers.{store}.scraper"
    )


def build_search_attempts(
    store: str,
    query: str,
) -> List[str]:

    raw = str(query or "").strip()
    normalized = norm(raw)

    attempts = []
    seen = set()

    def add(value: Any) -> None:
        value = str(value or "").strip()
        key = norm(value)

        if key and key not in seen:
            seen.add(key)
            attempts.append(value)

    add(raw)

    family = family_key(raw)

    if family:
        # Query famiglia standard.
        for term in FAMILY_SEARCH_TERMS.get(family, []):
            add(term)

        # Il catalogo può aggiungere varianti reali senza hard-coding.
        for name in catalog_family_names(raw):
            add(name)

        return attempts[:14]

    # Ricerca normale: poche query, perché ogni chiamata può essere costosa.
    tokens = _query_tokens(raw)

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

    # Brand scoperti dal catalogo: solo come fallback finale.
    for brand in catalog_brand_candidates(raw):
        add(brand)

    return attempts[:6]


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:

    module = load_scraper(store)

    attempts = build_search_attempts(
        store,
        query,
    )

    output = []
    seen = set()

    for attempt in attempts:

        try:
            results = module.search(attempt) or []
        except Exception:
            traceback.print_exc()
            continue

        for item in results:

            if not isinstance(item, dict):
                continue

            product = normalize_product(
                {
                    **item,
                    "store": item.get("store") or store,
                }
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

    # IMPORTANTE:
    # Non facciamo più "break" dopo il primo risultato.
    # Un negozio può restituire una variante in una query e un'altra
    # variante in una query successiva.
    return output


# ============================================================
# DEDUPLICAZIONE / ORDINAMENTO
# ============================================================

def unique_results(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

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


def sort_by_price(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:

    def key(product):
        value = price_num(product.get("price"))

        if value is None:
            return float("inf")

        return value

    return sorted(products, key=key)


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

    history = history_data.get(key, [])

    if not isinstance(history, list):
        history = []

    if not best_offer:
        return history

    point = {
        "date": datetime.now(
            timezone.utc
        ).isoformat(),
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
        "catalog_loaded": bool(CATALOG_PRODUCTS),
        "catalog_products": len(CATALOG_PRODUCTS),
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

    all_results = []
    errors = {}

    # --------------------------------------------------------
    # ARCHITETTURA DELLA RICERCA
    # --------------------------------------------------------
    # 4 worker invece di 2:
    # - gli 8 negozi possono avanzare in due ondate;
    # - non saturiamo subito la RAM come con 8 connessioni simultanee;
    # - il timeout è globale ma abbastanza largo da permettere alla
    #   seconda ondata di completare.
    #
    # Il catalogo NON limita i risultati.
    # Gli scraper restano la fonte dei prezzi.
    # --------------------------------------------------------

    max_workers = min(4, len(STORES))

    executor = ThreadPoolExecutor(
        max_workers=max_workers
    )

    futures = {
        executor.submit(
            run_store,
            store,
            query,
        ): store
        for store in STORES
    }

    # 55 secondi per la ricerca completa.
    # È volutamente più largo del vecchio 28s: con 4 worker gli ultimi
    # negozi devono avere il tempo di partire.
    search_timeout = 55

    try:

        for future in as_completed(
            futures,
            timeout=search_timeout,
        ):

            store = futures[future]

            try:
                store_results = future.result()

                if store_results:
                    all_results.extend(store_results)

            except Exception as error:

                errors[store] = (
                    f"{type(error).__name__}: {error}"
                )

                traceback.print_exc()

    except TimeoutError:

        # Non perdiamo ciò che è già arrivato.
        for future, store in futures.items():

            if future.done():
                continue

            errors[store] = (
                "Timeout: ricerca non completata entro 55 secondi"
            )

    finally:

        # I future già terminati vengono raccolti.
        # Quelli ancora in esecuzione non vengono aspettati oltre il limite.
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
                    "Timeout: negozio ancora in esecuzione",
                )

        executor.shutdown(
            wait=False,
            cancel_futures=True,
        )

    results = sort_by_price(
        unique_results(all_results)
    )

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }


# ============================================================
# API - TEST SINGOLO STORE
# ============================================================

@app.get("/test-store")
def test_store(
    store: str,
    q: str,
):

    store = str(store or "").strip().lower()
    query = str(q or "").strip()

    if store not in STORES:
        raise HTTPException(
            status_code=400,
            detail=(
                "Store non valido. Disponibili: "
                + ", ".join(STORES)
            ),
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
            "error": (
                f"{type(error).__name__}: {error}"
            ),
        }


# ============================================================
# API - SUGGEST / CATALOGO
# ============================================================

def fragella_search(
    query: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:

    api_key = os.getenv(
        "FRAGELLA_API_KEY",
        "",
    ).strip()

    if not api_key:
        return []

    params = urlencode({
        "search": query,
        "limit": max(
            1,
            min(int(limit), 10),
        ),
    })

    request = Request(
        "https://api.fragella.com/api/v1/fragrances?"
        + params,
        headers={
            "x-api-key": api_key,
            "Accept": "application/json",
            "User-Agent": "ScentHunter/1.0",
        },
    )

    with urlopen(
        request,
        timeout=5,
    ) as response:

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
            "catalog_id": (
                item.get("_id")
                or item.get("id")
            ),
        })

    return output


def rank_catalog_suggestions(
    items: List[Dict[str, Any]],
    query: str,
) -> List[Dict[str, Any]]:

    query_n = norm(query)

    tokens = [
        token
        for token in query_n.split()
        if len(token) >= 2
    ]

    ranked = []
    seen = set()

    for item in items:

        name = str(
            item.get("name") or ""
        ).strip()

        brand = str(
            item.get("brand") or ""
        ).strip()

        if not name:
            continue

        name_n = norm(name)
        brand_n = norm(brand)
        text = norm(
            f"{brand} {name}"
        )

        if tokens and not all(
            token in text
            for token in tokens
        ):
            continue

        if _is_non_perfume_name(name):
            continue

        key = (
            str(
                item.get("catalog_id")
                or ""
            ).strip()
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

    ranked.sort(
        key=lambda row: row[:4]
    )

    return [
        row[4]
        for row in ranked[:8]
    ]


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

                if (
                    len(token) >= 3
                    and token not in catalog_queries
                ):
                    catalog_queries.append(token)

            catalog_results = []
            catalog_seen = set()

            for catalog_query in catalog_queries:

                for item in fragella_search(
                    catalog_query,
                    10,
                ):

                    key = (
                        str(
                            item.get("catalog_id")
                            or ""
                        ).strip()
                        or (
                            f"{norm(item.get('brand'))}|"
                            f"{norm(item.get('name'))}"
                        )
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

            print(
                "Catalog suggest error:",
                repr(error),
            )

        except Exception:

            traceback.print_exc()

    # Fallback ai negozi.
    suggestions = []
    seen = set()

    for store in STORES:

        try:

            module = load_scraper(store)

            results = module.search(
                raw_query
            ) or []

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

                brand = str(
                    product.get("brand")
                    or ""
                ).strip()

                haystack = norm(
                    f"{brand} {name}"
                )

                words = [
                    word
                    for word in query.split()
                    if word
                ]

                if not all(
                    word in haystack
                    for word in words
                ):
                    continue

                if _is_non_perfume_name(name):
                    continue

                key = (
                    norm(brand),
                    norm(name),
                )

                if key in seen:
                    continue

                seen.add(key)

                suggestions.append({
                    "name": name,
                    "store": product.get(
                        "store",
                        store,
                    ),
                    "brand": brand,
                    "image": product_image(product),
                })

        except Exception:

            traceback.print_exc()

    suggestions.sort(
        key=lambda item: (
            0
            if norm(
                item.get("name", "")
            ).startswith(query)
            else 1,
            len(
                item.get("name", "")
            ),
            item.get(
                "name",
                "",
            ).lower(),
        )
    )

    suggestions = suggestions[:8]

    return {
        "query": q,
        "count": len(suggestions),
        "suggestions": suggestions,
        "source": "stores-fallback",
    }


# ============================================================
# API - AUTOCOMPLETE
# ============================================================

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

    data = search_perfume(name)

    offers = []

    for product_data in data["results"]:

        value = price_num(
            product_data.get("price")
        )

        if value is None:
            continue

        offer = dict(product_data)

        offer["price_value"] = value
        offer["image"] = product_image(
            offer
        )

        offers.append(offer)

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
