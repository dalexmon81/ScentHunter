from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import traceback
import unicodedata
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
MASTER_CATALOG_PATH = os.path.join(BASE_DIR, "ScentHunter_catalogo_master_V5_FAMIGLIE.json")

FRONTEND_INDEX = (
    Path(__file__).resolve().parent.parent
    / "frontend"
    / "index.html"
)

# Varianti che rendono la query specifica. Senza marker la ricerca è di famiglia.
VARIANT_MARKERS = {
    "pour femme", "pour homme", "femme", "homme", "flame", "night",
    "night out", "by night", "rebel", "elixir", "intense", "extreme",
    "limited", "limited edition", "collector", "collector edition",
    "collector's edition", "special edition", "anniversary", "ice",
    "blanc", "noir", "nude", "rose", "blue", "red", "black", "white",
    "gold", "silver", "coral", "fantasy", "sport", "absolu",
    "le parfum", "the parfum", "the most", "most wanted",
}
VARIANTS = VARIANT_MARKERS

NON_PERFUME = {
    # Prodotti di cura/corpo che NON devono entrare nelle ricerche
    # dei profumi. I set/coffret/bundle/kit restano invece ammessi.
    "deodorant",
    "deostick",
    "deo stick",
    "deodorant stick",
    "deo spray",
    "shampoo",
    "conditioner",
    "hair conditioner",
    "hair care",
    "hair",
    "shower gel",
    "duschgel",
    "dusch gel",
    "duschbad",
    "shower",
    "body wash",
    "body lotion",
    "body cream",
    "body butter",
    "body milk",
    "body oil",
    "body mist",
    "hand cream",
    "hand wash",
    "hand lotion",
    "after shave",
    "aftershave",
    "beard",
    "soap",
    "bath",
    "bath oil",
    "bath gel",
    "oil",
    "öl",
    "oel",
    "körperöl",
    "koerperoel",
    "fragrance oil",
    "perfume oil",
    "cream",
    "creme",
    "körpercreme",
    "koerpercreme",
    "lotion",
    "körperlotion",
    "koerperlotion",
    "candle",
    "diffuser",
    "room spray",
    "home fragrance",
    "fabric spray",
    "scrub",
    "toothpaste",
    "detergent",
    "powder",
    "talc",
    "roll on",
    "roll-on",
}

# I set/coffret/bundle/kit sono ammessi anche se contengono prodotti
# accessori: l'utente ha scelto esplicitamente di lasciarli nei risultati.
SET_MARKERS = {
    "set",
    "coffret",
    "bundle",
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
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))

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
# NORMALIZZAZIONE NOME VISUALIZZATO
# ============================================================

def display_name(product: Dict[str, Any]) -> str:
    """
    Restituisce il nome canonico visualizzato da ScentHunter.

    Regola: il nome del profumo viene prima di eventuali descrittori
    iniziali come Uomo/Donna; il brand resta nel campo brand e quindi
    il frontend può visualizzare: Brand - Nome profumo - resto.
    """
    brand = str(product.get("brand") or "").strip()
    raw_name = str(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
        or ""
    ).strip()

    if not raw_name:
        return ""

    # Elimina un eventuale brand già incorporato nel nome.
    if brand:
        raw_name = re.sub(
            rf"^\s*{re.escape(brand)}\s*[-–—:]?\s*",
            "",
            raw_name,
            flags=re.IGNORECASE,
        ).strip()

    # Caso importante per Born in Roma: alcuni negozi scrivono
    # "Donna Born in Roma ..." / "Uomo Born in Roma ...".
    # Il formato canonico deve essere "Born in Roma Donna ..." /
    # "Born in Roma Uomo ...".
    match = re.match(
        r"^(donna|uomo)\s+(born\s+in\s+roma)(?:\s+(.*))?$",
        raw_name,
        flags=re.IGNORECASE,
    )
    if match:
        gender = match.group(1).title()
        family = "Born in Roma"
        rest = (match.group(3) or "").strip()
        return " ".join(part for part in (family, rest, gender) if part)

    # Copre anche il caso opposto: "Born in Roma Uomo ...".
    match = re.match(
        r"^(born\s+in\s+roma)\s+(donna|uomo)(?:\s+(.*))?$",
        raw_name,
        flags=re.IGNORECASE,
    )
    if match:
        family = "Born in Roma"
        gender = match.group(2).title()
        rest = (match.group(3) or "").strip()
        return " ".join(part for part in (family, rest, gender) if part)

    return raw_name


def normalize_product_names(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Applica il nome canonico senza alterare gli altri dati del prodotto."""
    normalized: List[Dict[str, Any]] = []
    for product in products:
        item = dict(product)
        name = display_name(item)
        if name:
            item["name"] = name
        normalized.append(item)
    return normalized


# ============================================================
# FILTRO RISULTATI
# ============================================================

def _query_has_variant_marker(query: str) -> bool:
    q = norm(query)
    return any(norm(marker) in q for marker in VARIANT_MARKERS)


def _is_set_product(product: Dict[str, Any]) -> bool:
    text = norm(" ".join(
        str(product.get(field) or "")
        for field in (
            "name", "title", "product_name", "description",
            "category", "type", "product_type",
        )
    ))
    return any(norm(marker) in text for marker in SET_MARKERS)


def _product_search_text(product: Dict[str, Any]) -> str:
    # Per il filtro usiamo solo i campi che identificano il prodotto.
    # La descrizione viene esclusa: può parlare di un set o di una linea
    # e contenere parole come "cream" / "shower gel" senza significare
    # che il risultato principale sia una crema o uno shower gel.
    return norm(" ".join(
        str(product.get(field) or "")
        for field in (
            "name", "title", "product_name",
            "category", "type", "product_type",
        )
    ))


def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Applica tre regole: famiglia, variante specifica e filtro prodotti.

    - Query base (es. Eros / Born in Roma) = accetta tutte le varianti
      che lo scraper restituisce.
    - Query con variante (es. Eros Flame) = resta specifica.
    - Deodoranti, shampoo, oli, creme, shower gel ecc. vengono esclusi.
      I set/coffret/bundle/kit sono volutamente ammessi.
    """
    name = norm(product.get("name", ""))
    query_normalized = norm(query)

    if not name:
        return False

    searchable = _product_search_text(product)

    if not _is_set_product(product):
        for phrase in NON_PERFUME:
            normalized_phrase = norm(phrase)
            if normalized_phrase and normalized_phrase in searchable:
                return False

    tokens = [
        token
        for token in query_normalized.split()
        if token not in IGNORED_WORDS
    ]
    if not tokens:
        return False

    # Se l'utente ha indicato una variante, non permettiamo che una
    # variante diversa della stessa famiglia passi il filtro.
    if _query_has_variant_marker(query):
        for phrase in VARIANT_MARKERS:
            normalized_phrase = norm(phrase)
            if (
                normalized_phrase
                and normalized_phrase in name
                and normalized_phrase not in query_normalized
            ):
                return False

    return all(token in name for token in tokens)

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


def load_master_catalog() -> List[Dict[str, Any]]:
    """Legge il catalogo master locale usato come sorgente delle famiglie."""
    try:
        with open(MASTER_CATALOG_PATH, "r", encoding="utf-8") as file:
            payload = json.load(file)
        items = payload.get("products", []) if isinstance(payload, dict) else []
        return [item for item in items if isinstance(item, dict)]
    except Exception:
        return []


def catalog_family_hints(query: str) -> List[str]:
    """Restituisce i nomi canonici del catalogo appartenenti alla famiglia cercata."""
    query_n = norm(query)
    if not query_n:
        return []

    query_tokens = [token for token in query_n.split() if token not in IGNORED_WORDS]
    if not query_tokens:
        return []

    hints: List[str] = []
    seen = set()
    for item in load_master_catalog():
        name = str(item.get("name") or "").strip()
        brand = str(item.get("brand") or "").strip()
        if not name:
            continue
        text = norm(f"{brand} {name}")
        if all(token in text for token in query_tokens):
            key = norm(name)
            if key and key not in seen:
                seen.add(key)
                hints.append(name)
    return hints


def build_search_attempts(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
) -> List[str]:
    """Costruisce query complementari per non perdere le varianti di famiglia."""
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()
        value_norm = norm(value)
        if value_norm and value_norm not in {norm(x) for x in attempts}:
            attempts.append(value)

    add(raw)

    # Il catalogo esterno può fornire altre varianti della famiglia.
    # Usiamo il solo nome, non la coppia Brand + Nome, per non bruciare
    # tentativi duplicati.
    for hint in catalog_hints or []:
        add(hint)

    tokens = [t for t in normalized.split() if t not in IGNORED_WORDS]

    if tokens:
        add(" ".join(tokens))

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

    # Limite prudente: abbastanza alto per una famiglia, ma senza
    # moltiplicare inutilmente le chiamate ai negozi.
    return attempts[:12]


def run_store(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Esegue più strategie di ricerca sullo stesso negozio e unisce i risultati pertinenti."""
    module = load_scraper(store)
    attempts = build_search_attempts(store, query, catalog_hints)
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
            seen.add(key)
            if matches(product, query):
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
        return {"query": "", "count": 0, "results": [], "errors": {}}

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    # Il catalogo master locale è la sorgente primaria delle famiglie.
    # Se una famiglia non è ancora completa nel master, Fragella viene usata
    # solo come fallback per aggiungere eventuali nomi mancanti.
    catalog_hints = catalog_family_hints(query)
    try:
        external_items = fragella_search(query, 30)
        seen_hints = {norm(item) for item in catalog_hints}
        query_n = norm(query)
        for item in external_items:
            name = str(item.get("name") or "").strip()
            brand = str(item.get("brand") or "").strip()
            if not name:
                continue
            text = norm(f"{brand} {name}")
            if query_n and not all(token in text for token in query_n.split()):
                continue
            hint_n = norm(name)
            if hint_n and hint_n not in seen_hints:
                seen_hints.add(hint_n)
                catalog_hints.append(name)
    except Exception:
        pass

    # NON 8 insieme: su Render Free abbiamo osservato exit 137.
    # Due worker riducono nettamente RAM e connessioni simultanee.
    executor = ThreadPoolExecutor(max_workers=2)
    futures = {
        executor.submit(run_store, store, query, catalog_hints): store
        for store in STORES
    }

    try:
        for future in as_completed(futures, timeout=28):
            store = futures[future]
            try:
                all_results.extend(future.result())
            except Exception as error:
                errors[store] = f"{type(error).__name__}: {error}"
                traceback.print_exc()
    except TimeoutError:
        pass
    finally:
        for future, store in futures.items():
            if not future.done():
                if future.cancel():
                    errors[store] = "Non eseguito: limite tempo ricerca"
                else:
                    errors[store] = "Timeout: negozio troppo lento"
        executor.shutdown(wait=False, cancel_futures=True)

    # Nome canonico + ordine alfabetico rigoroso:
    # Brand -> nome profumo -> resto del nome -> negozio -> prezzo.
    results = normalize_product_names(
        unique_results(all_results)
    )
    results.sort(
        key=lambda product: (
            norm(product.get("brand", "")),
            norm(product.get("name", "")),
            norm(product.get("store", "")),
            price_num(product.get("price"))
            if price_num(product.get("price")) is not None
            else float("inf"),
        )
    )

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "errors": errors,
    }


# ============================================================
# API - TEST SINGOLO STORE (diagnostica)
# ============================================================

@app.get("/test-store")
def test_store(store: str, q: str):
    """
    Endpoint diagnostico: esegue UN SOLO scraper.
    Non modifica la normale ricerca /search.
    """
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
        results = run_store(store, query)
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
# API - SUGGEST
# ============================================================

def fragella_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """
    Catalogo profumi indipendente dai negozi.
    Serve SOLO all'autocomplete: la ricerca prezzi resta affidata agli scraper.
    """
    api_key = os.getenv("FRAGELLA_API_KEY", "").strip()

    if not api_key:
        return []

    params = urlencode({
        "search": query,
        "limit": max(1, min(int(limit), 30)),
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

    output: List[Dict[str, Any]] = []

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
        name = str(item.get("name") or "").strip()
        brand = str(item.get("brand") or "").strip()

        if not name:
            continue

        name_n = norm(name)
        brand_n = norm(brand)
        text = norm(f"{brand} {name}")

        if tokens and not all(token in text for token in tokens):
            continue

        if not _is_set_product(item):
            suggestion_text = _product_search_text(item)
            if any(
                norm(phrase) in suggestion_text
                for phrase in NON_PERFUME
            ):
                continue

        key = (
            str(item.get("catalog_id") or "").strip()
            or f"{brand_n}|{name_n}"
        )

        if key in seen:
            continue

        seen.add(key)

        # Priorità:
        # 1) nome profumo che inizia esattamente con ciò che si scrive
        # 2) brand che inizia con ciò che si scrive
        # 3) query contenuta nel nome
        # 4) query contenuta nel brand
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

    # --------------------------------------------------------
    # 1. CATALOGO PROFUMI
    # --------------------------------------------------------
    # Non dipende dai negozi. Quindi "Aquatica", "Liquid Brun",
    # "Hawas Ice", ecc. possono comparire anche se uno scraper
    # prezzi in quel momento è lento o non risponde.
    if len(query) >= 3:
        try:
            catalog_queries = [raw_query]

            # Per ricerche tipo "French Avenue Liquid Brun"
            # proviamo anche le parole significative.
            for token in query.split():
                if len(token) >= 3 and token not in catalog_queries:
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

    # --------------------------------------------------------
    # 2. FALLBACK NEGOZI
    # --------------------------------------------------------
    # Se il catalogo esterno non è disponibile, manteniamo il
    # comportamento che già funzionava nel main(10).
    suggestions = []
    seen = set()

    for store in STORES:
        try:
            module = load_scraper(store)

            attempts = [raw_query]

            if query not in attempts:
                attempts.append(query)

            for attempt in attempts:
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

                    normalized_name = norm(name)
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

                    if not _is_set_product(product):
                        suggestion_text = _product_search_text(product)
                        if any(
                            norm(phrase) in suggestion_text
                            for phrase in NON_PERFUME
                        ):
                            continue

                    key = (
                        norm(brand),
                        normalized_name,
                    )

                    if key in seen:
                        continue

                    seen.add(key)

                    suggestion_name = display_name(product) or name
                    suggestions.append({
                        "name": suggestion_name,
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
            if norm(item.get("name", "")).startswith(query)
            else 1,
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
