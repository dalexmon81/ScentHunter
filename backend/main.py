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
    "kobra",
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


CATALOG_ALIASES: Dict[str, str] = {}
CATALOG_BRANDS: Dict[str, str] = {}
CATALOG_PRODUCTS: List[Dict[str, Any]] = []
CATALOG_FAMILY_FORMS: List[str] = []


SET_PRODUCTS = {
    "gift set", "set regalo", "coffret", "bundle", "travel set",
    "discovery set", "kit",
}

NON_PERFUME = {
    # Deodoranti / antitraspiranti
    "deodorant", "deodorante", "deodorants", "deodorantes", "déodorant",
    "deo", "deo spray", "deo stick", "deostick", "deodorant stick",
    "deodorant spray", "deodorant roll on", "antiperspirant",
    "antitranspirant", "anti transpirant", "anti-transpirant",
    # Doccia / bagno / capelli (incluse le forme tedesche)
    "shampoo", "shampo", "conditioner", "hair conditioner", "hair care",
    "hair", "shower gel", "showergel", "gel douche", "gel doccia",
    "doccia gel", "duschgel", "dusch gel", "duschbad", "dusch bad",
    "shower", "body wash", "body gel", "bath", "bath gel", "bath oil",
    "bagnoschiuma", "bagno schiuma", "douche", "gel da bagno",
    # Creme / lozioni / trattamenti corpo-viso-mani (incluse forme tedesche)
    "body lotion", "body cream", "body creme", "body butter", "body milk",
    "body moisturizer", "body moisturiser", "body balm", "body mist",
    "hair mist", "face mist", "fragrance mist", "body splash",
    "hand cream", "hand creme", "hand lotion", "face cream", "face creme",
    "face lotion", "face wash", "facial cream", "facial lotion",
    "cream", "creme", "crème", "crema", "creme hydratante",
    "lotion", "lozione", "locion", "lotion corps", "moisturizer",
    "moisturiser", "emulsion", "émulsion", "emulsione", "serum", "siero",
    "balsam", "balm", "baume", "körperlotion", "körper lotion",
    "körpercreme", "körper creme", "gesichtscreme", "gesicht creme",
    "handcreme", "haarshampoo",
    # Oli
    "body oil", "oil", "huile", "olio", "fragrance oil", "perfume oil",
    "essential oil", "huile essentielle", "körperöl", "körper öl",
    # Saponi / barba / igiene
    "soap", "savon", "sapone", "seife", "shaving", "shave",
    "after shave", "aftershave", "beard", "barba", "rasage", "razor",
    "roll on", "roll-on", "rasier",
    # Altri cosmetici / casa
    "candle", "diffuser", "room spray", "home fragrance", "fabric spray",
    "scrub", "cleanser", "mask", "toothpaste", "toothbrush", "detergent",
    "powder", "talc",
}


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
        if str(candidate) not in seen:
            seen.add(str(candidate))
            unique.append(candidate)
    return unique


def _word_tokens(value: Any) -> List[str]:
    return re.findall(r"[A-Za-zÀ-ÿ0-9]+(?:['’][A-Za-zÀ-ÿ0-9]+)?", str(value or ""))


def _load_catalog() -> None:
    global CATALOG_PRODUCTS, CATALOG_ALIASES, CATALOG_BRANDS, CATALOG_FAMILY_FORMS
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
    CATALOG_PRODUCTS = [item for item in products if isinstance(item, dict)]
    forms = set()
    for item in CATALOG_PRODUCTS:
        brand = str(item.get("brand") or "").strip()
        canonical = str(item.get("name") or "").strip()
        if not canonical:
            continue
        candidates = [canonical]
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            candidates.extend(str(alias or "").strip() for alias in aliases)
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
        forms.add(canonical)
    CATALOG_FAMILY_FORMS = sorted(forms, key=lambda value: len(norm(value).split()), reverse=True)


_load_catalog()


def _catalog_brand_candidates(query: str) -> List[str]:
    q_tokens = [token for token in norm(query).split() if token not in IGNORED_WORDS]
    if not q_tokens:
        return []

    # Per una variante specifica, se il catalogo non contiene quella variante,
    # togliamo solo i marcatori generici e risaliamo comunque al brand della famiglia.
    # Nessun profumo è hard-coded.
    core_tokens = [
        token for token in q_tokens
        if not any(token == marker_token for marker in VARIANT_MARKERS for marker_token in norm(marker).split())
    ]
    search_sets = [q_tokens]
    if core_tokens and core_tokens != q_tokens:
        search_sets.append(core_tokens)

    brands = []
    seen = set()
    for search_tokens in search_sets:
        for item in CATALOG_PRODUCTS:
            brand = str(item.get("brand") or "").strip()
            name = str(item.get("name") or "").strip()
            text = norm(f"{brand} {name}")
            if brand and all(token in text for token in search_tokens):
                key = norm(brand)
                if key not in seen:
                    seen.add(key)
                    brands.append(brand)
    return brands[:4]


def _catalog_family_candidates(query: str) -> List[str]:
    """
    Restituisce TUTTE le denominazioni del catalogo che appartengono alla
    famiglia cercata. Non contiene nomi di profumi hard-coded.

    La sorgente primaria è il catalogo locale. Se disponibile, Fragella viene
    usato solo per ampliare il catalogo della famiglia; il risultato completo
    viene poi passato agli scraper come serie di query separate.
    """
    query_tokens = [
        token for token in norm(query).split()
        if token not in IGNORED_WORDS
    ]
    if not query_tokens:
        return []

    candidates: List[str] = []
    seen = set()

    def add(value: Any, brand: str = "") -> None:
        name = str(value or "").strip()
        if not name:
            return
        # Preferiamo il solo nome del profumo: il filtro finale continuerà
        # comunque a verificare che la famiglia richiesta sia presente.
        key = norm(name)
        if key and key not in seen:
            seen.add(key)
            candidates.append(name)

    # 1) Catalogo locale
    for item in CATALOG_PRODUCTS:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        brand = str(item.get("brand") or "").strip()
        if not name:
            continue
        text = norm(f"{brand} {name}")
        if all(token in text for token in query_tokens):
            add(name, brand)
        aliases = item.get("aliases")
        if isinstance(aliases, list):
            for alias in aliases:
                alias_text = norm(f"{brand} {alias}")
                if all(token in alias_text for token in query_tokens):
                    add(name, brand)

    # 2) Catalogo remoto: non ci fermiamo al primo record.
    #    Questo è il punto che evita il caso "Eros + Eros Flame" soltanto.
    try:
        remote_items = fragella_search(query, 50)
        for item in remote_items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            brand = str(item.get("brand") or "").strip()
            if not name:
                continue
            text = norm(f"{brand} {name}")
            if all(token in text for token in query_tokens):
                add(name, brand)
    except Exception:
        pass

    # Più specifico prima, poi ordine alfabetico stabile.
    candidates.sort(key=lambda value: (-len(norm(value).split()), norm(value)))
    return candidates


def product_search_text(product: Dict[str, Any]) -> str:
    """
    Testo completo utile per i filtri: alcuni scraper possono avere
    la variante nel titolo, nell'URL o in un campo secondario.
    """
    values = (
        product.get("name"),
        product.get("title"),
        product.get("product_name"),
        product.get("url"),
        product.get("product_line"),
        product.get("variant"),
        product.get("size"),
        product.get("size_ml"),
        product.get("volume"),
        product.get("volume_ml"),
        product.get("format"),
        product.get("format_ml"),
        product.get("pack_size"),
    )

    # Alcuni scraper possono mettere la taglia dentro attributes.
    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        values += tuple(
            value
            for key, value in attributes.items()
            if any(token in norm(key) for token in ("size", "volume", "format"))
        )

    return norm(" ".join(str(value or "") for value in values))


def has_small_size(product: Dict[str, Any]) -> bool:
    """
    Esclude campioni/mini-taglie fino a 10 ml, salvo ricerca esplicita
    della taglia.
    """
    text = product_search_text(product)

    for match in re.finditer(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b", text):
        try:
            if float(match.group(1).replace(",", ".")) <= 10:
                return True
        except ValueError:
            continue

    return False


# ============================================================
# FILTRO RISULTATI
# ============================================================

def matches(product: Dict[str, Any], query: str) -> bool:
    """
    Filtro preciso ma non eccessivamente restrittivo.

    La query puo' indicare una famiglia (es. "Liquid Brun"): in quel caso
    le varianti della stessa famiglia restano ammesse. Se invece la query
    indica esplicitamente una variante (es. "Liquid Brun Limited Edition"),
    non vengono accettate altre varianti.
    """
    item = dict(product)
    name = norm(item.get("name", ""))
    query_normalized = norm(query)

    if not name:
        return False

    # Mini-taglie/campioni fino a 10 ml: escluse salvo ricerca esplicita.
    query_has_size = bool(
        re.search(r"(?<!\d)\d+(?:[.,]\d+)?\s*ml\b", query_normalized)
    )
    if has_small_size(item) and not query_has_size:
        return False

    # I prodotti non-profumo restano esclusi.
    search_text = product_search_text(item)
    if any(norm(phrase) in name for phrase in NON_PERFUME if norm(phrase)):
        return False

    # Se la query specifica una concentrazione, deve coincidere.
    def concentration(value: str) -> str:
        text = norm(value)
        if re.search(r"\beau de parfum\b|\bedp\b", text):
            return "edp"
        if re.search(r"\beau de toilette\b|\bedt\b", text):
            return "edt"
        if re.search(r"\bextrait(?: de parfum)?\b", text):
            return "extrait"
        return ""

    query_concentration = concentration(query_normalized)
    if query_concentration and concentration(name) != query_concentration:
        return False

    # Conserviamo i sinonimi di genere nel matching.
    matching_name = name
    if "donna" in name.split():
        matching_name += " femme women woman"
    if "uomo" in name.split():
        matching_name += " femme homme men man"
    matching_name = norm(matching_name)

    tokens = [t for t in query_normalized.split() if t not in IGNORED_WORDS]
    brand = norm(item.get("brand") or "")
    if brand:
        brand_tokens = set(brand.split())
        tokens = [t for t in tokens if t not in brand_tokens]

    if not tokens:
        return False

    if not all(token in matching_name for token in tokens):
        return False

    # SOLO se la query specifica una variante, impediamo che entri un'altra
    # variante. Per una query di famiglia, invece, Limited Edition ecc.
    # devono poter essere recuperate.
    query_has_variant = any(norm(marker) in query_normalized for marker in VARIANTS if norm(marker))
    if query_has_variant:
        query_tokens = set(tokens)
        name_tokens = set(name.split())
        for marker in VARIANTS:
            marker_norm = norm(marker)
            if marker_norm in {"parfum", "extrait", "edp", "edt", "eau de parfum", "eau de toilette"}:
                continue
            marker_tokens = set(marker_norm.split())
            if marker_tokens and marker_tokens.issubset(name_tokens) and not marker_tokens.issubset(query_tokens):
                return False

    return True


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


def build_search_attempts(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
    discovered_brands: Optional[List[str]] = None,
    family_candidates: Optional[List[str]] = None,
) -> List[str]:
    """Costruisce query mirate, incluse le diverse referenze della famiglia."""
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()
        value_norm = norm(value)
        if value_norm and value_norm not in {norm(x) for x in attempts}:
            attempts.append(value)

    add(raw)

    # Se il catalogo conosce piu' referenze della stessa famiglia, le
    # interroghiamo separatamente. E' il passaggio che permette di recuperare
    # anche Liquid Brun Limited Edition quando la query e' solo "Liquid Brun".
    if family_candidates:
        for family_name in family_candidates[:6]:
            add(family_name)
        for hint in (catalog_hints or [])[:1]:
            add(hint)
        return attempts[:8]

    for brand in discovered_brands or []:
        add(brand)
        add(f"{brand} {raw}")

    tokens = [t for t in normalized.split() if t not in IGNORED_WORDS]
    if tokens:
        add(" ".join(tokens))
    if len(tokens) >= 2:
        add(" ".join(tokens[1:]))
    if len(tokens) >= 3:
        add(" ".join(tokens[-2:]))

    compact = re.sub(r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)", "", normalized)
    if compact != normalized:
        add(compact)

    return attempts[:8]


def run_store(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
    family_candidates: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Ricerca iniziale + tutte le varianti mirate della famiglia."""
    module = load_scraper(store)
    raw_query = str(query or "").strip()

    initial_results = module.search(raw_query) or []
    discovered_brands: List[str] = []

    if not family_candidates:
        seen_brands = set()
        for item in initial_results:
            if isinstance(item, dict):
                brand = str(item.get("brand") or "").strip()
                if brand and norm(brand) not in seen_brands:
                    seen_brands.add(norm(brand))
                    discovered_brands.append(brand)
        for brand in _catalog_brand_candidates(raw_query):
            if norm(brand) not in seen_brands:
                seen_brands.add(norm(brand))
                discovered_brands.append(brand)

    attempts = build_search_attempts(
        store, raw_query, catalog_hints, discovered_brands, family_candidates
    )

    output: List[Dict[str, Any]] = []
    seen = set()

    # IMPORTANTISSIMO: non interrompiamo al primo risultato.
    # Dobbiamo completare la raccolta delle varianti della famiglia.
    batches = [(raw_query, initial_results)]
    for attempt in attempts:
        if norm(attempt) == norm(raw_query):
            continue
        try:
            batches.append((attempt, module.search(attempt) or []))
        except Exception:
            continue

    for attempt, results in batches:
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

            if matches(product, raw_query):
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

    catalog_hints = _catalog_brand_candidates(query)
    family_candidates = _catalog_family_candidates(query)

    # Come nel flusso stabile: tutti gli store lavorano in parallelo, ma
    # ogni store completa tutte le query mirate prima di restituire i risultati.
    executor = ThreadPoolExecutor(max_workers=2)
    futures = {
        executor.submit(
            run_store,
            store,
            query,
            catalog_hints,
            family_candidates,
        ): store
        for store in STORES
    }

    try:
        for future in as_completed(futures, timeout=60):
            store = futures[future]
            try:
                all_results.extend(future.result() or [])
            except Exception as error:
                errors[store] = f"{type(error).__name__}: {error}"
                traceback.print_exc()
    except TimeoutError:
        for future, store in futures.items():
            if not future.done():
                errors[store] = "timeout"
                future.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    # Manteniamo l'ordinamento per prezzo del main nuovo.
    unique: List[Dict[str, Any]] = []
    seen = set()
    for product in all_results:
        key = (
            str(product.get("store", "")).lower(),
            str(product.get("url", "")).lower(),
            norm(product.get("name", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(product)

    unique.sort(
        key=lambda product: (
            float("inf") if price_num(product.get("price")) is None else price_num(product.get("price"))
        )
    )

    return {
        "query": query,
        "count": len(unique),
        "results": unique,
        "comparisons": [],
        "errors": errors,
    }

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

        if any(
            norm(phrase) in name_n
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

                    if any(
                        norm(phrase) in normalized_name
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
