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

# ============================================================
# RICERCA PER LINEE / FAMIGLIE
# ============================================================

LINE_FAMILY_PLANS = {
    "9 pm": {
        "brand": "afnan",
        "terms": [
            "9 PM", "9PM", "Afnan 9 PM",
            "9PM Elixir", "9PM Night Out", "9PM Rebel",
            "9 PM Pour Femme", "9PM Pour Femme",
            "9 PM Purple Femme", "9PM Purple Femme",
            "Purple Femme",
        ],
    },
    "9 am": {
        "brand": "afnan",
        "terms": [
            "9 AM", "9AM", "Afnan 9 AM",
            "9 AM Dive", "9 AM Pour Femme",
        ],
    },
    "le beau": {
        "brand": "jean paul gaultier",
        "terms": [
            "Le Beau", "Jean Paul Gaultier Le Beau",
            "Le Beau Le Parfum", "Le Beau Le Parfum Intense",
            "Le Beau Paradise Garden", "Le Beau Narcisse",
            "Le Beau Narcisse Eau de Parfum", "Narcisse Le Beau",
        ],
    },
}

def family_search_plan(query: str) -> Optional[Dict[str, Any]]:
    normalized = norm(query)
    if re.search(r"(?:^|\s)9\s*pm(?:\s|$)", normalized):
        return LINE_FAMILY_PLANS["9 pm"]
    if re.search(r"(?:^|\s)9\s*am(?:\s|$)", normalized):
        return LINE_FAMILY_PLANS["9 am"]
    if re.search(r"\ble\s+beau\b", normalized):
        return LINE_FAMILY_PLANS["le beau"]
    return None


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


# ============================================================
# CATALOGO MASTER / NORMALIZZAZIONE NOMI
# ============================================================

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


def _catalog_family_form(query: str) -> str:
    q_tokens = [token for token in norm(query).split() if token not in IGNORED_WORDS]
    if not q_tokens:
        return str(query or "").strip()
    best = None
    for item in CATALOG_PRODUCTS:
        canonical = str(item.get("name") or "").strip()
        if not canonical:
            continue
        original_tokens = _word_tokens(canonical)
        normalized_tokens = norm(canonical).split()
        for index in range(len(normalized_tokens) - len(q_tokens) + 1):
            if normalized_tokens[index:index + len(q_tokens)] == q_tokens:
                best = " ".join(original_tokens[index:index + len(q_tokens)])
                return best
    return str(query or "").strip()


def _move_gender_after_family(name: str, family_query: str = "") -> str:
    """
    Porta SEMPRE il genere alla fine del nome del profumo.

    Formato rigoroso ScentHunter:
        Brand - Nome profumo - tutto il resto - Genere

    Esempi:
        Donna Born In Roma Coral Fantasy -> Born in Roma Coral Fantasy Donna
        Uomo Born In Roma Coral Fantasy -> Born in Roma Coral Fantasy Uomo
        Born In Roma Donna Coral Fantasy -> Born in Roma Coral Fantasy Donna
        Born In Roma Uomo Extradose -> Born in Roma Extradose Uomo
        Born In Roma Intense Uomo -> Born in Roma Intense Uomo
    """
    raw = re.sub(r"\s+", " ", str(name or "")).strip()
    if not raw:
        return raw

    gender_re = re.compile(r"\b(uomo|donna|men|women|man|woman|homme|femme)\b", re.I)
    matches = list(gender_re.finditer(raw))
    if not matches:
        return raw

    # Prendiamo il primo indicatore di genere e lo rimuoviamo da qualsiasi
    # posizione. Il genere viene poi sempre aggiunto in coda al nome completo.
    gender_map = {
        "uomo": "Uomo", "donna": "Donna",
        "men": "Uomo", "man": "Uomo",
        "women": "Donna", "woman": "Donna",
        "homme": "Uomo", "femme": "Donna",
    }
    gender = gender_map[matches[0].group(1).lower()]
    without_gender = gender_re.sub(" ", raw)
    without_gender = re.sub(r"\s+", " ", without_gender).strip()

    # Il catalogo può fornire la forma canonica della famiglia (es. Born in Roma).
    # Qui NON rimettiamo il genere in mezzo: deve stare sempre alla fine.
    family_tokens = [token for token in norm(family_query).split() if token not in IGNORED_WORDS]
    base_tokens = norm(without_gender).split()
    original_tokens = _word_tokens(without_gender)

    if family_tokens and len(base_tokens) >= len(family_tokens):
        for index in range(len(base_tokens) - len(family_tokens) + 1):
            if base_tokens[index:index + len(family_tokens)] != family_tokens:
                continue
            family_text = _catalog_family_form(family_query) if family_query else " ".join(original_tokens[index:index + len(family_tokens)])
            before = " ".join(original_tokens[:index]).strip()
            after = " ".join(original_tokens[index + len(family_tokens):]).strip()
            parts = [before, family_text, after, gender]
            return " ".join(part for part in parts if part).strip()

    # Se non riusciamo a ricostruire la famiglia, manteniamo tutto il nome
    # nell'ordine originale, ma il genere viene comunque portato in coda.
    return f"{without_gender} {gender}".strip()


def canonical_product_brand(product: Dict[str, Any]) -> str:
    raw_name = str(product.get("name") or product.get("title") or product.get("product_name") or "").strip()
    brand = str(product.get("brand") or "").strip()
    return (
        CATALOG_BRANDS.get(norm(raw_name))
        or CATALOG_BRANDS.get(norm(f"{brand} {raw_name}"))
        or brand
    ).strip()


def canonical_product_name(product: Dict[str, Any], family_query: str = "") -> str:
    raw_name = str(product.get("name") or product.get("title") or product.get("product_name") or "").strip()
    brand = canonical_product_brand(product)
    if not raw_name:
        return ""
    canonical = CATALOG_ALIASES.get(norm(raw_name)) or CATALOG_ALIASES.get(norm(f"{brand} {raw_name}"))
    name = canonical or raw_name
    if brand:
        name = re.sub(rf"^\s*{re.escape(brand)}\s*[-–—:]?\s*", "", name, flags=re.I).strip()
    name = _move_gender_after_family(name, family_query)
    words = name.split()
    collapsed = []
    for word in words:
        if collapsed and norm(collapsed[-1]) == norm(word):
            continue
        collapsed.append(word)
    name = " ".join(collapsed)
    return re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", name).strip()


def normalize_product(product: Dict[str, Any], family_query: str = "") -> Dict[str, Any]:
    item = dict(product)
    item["brand"] = canonical_product_brand(item)
    item["name"] = canonical_product_name(item, family_query)
    brand = str(item.get("brand") or "").strip()
    name = str(item.get("name") or "").strip()
    item["display_name"] = f"{brand} - {name}" if brand else name
    return item


# ============================================================
# FILTRO RISULTATI
# ============================================================

def _query_has_variant_marker(query: str) -> bool:
    q = norm(query)
    return any(norm(marker) in q for marker in VARIANT_MARKERS if norm(marker))


def _contains_term(text: str, phrase: str) -> bool:
    """
    Cerca una parola/frase come termine reale, non come semplice sottostringa.
    Evita falsi positivi mentre intercetta anche forme come Duschgel/Deostick.
    """
    text_n = norm(text)
    phrase_n = norm(phrase)
    if not text_n or not phrase_n:
        return False
    return bool(re.search(r"(?<![a-z0-9])" + re.escape(phrase_n) + r"(?![a-z0-9])", text_n))


def _is_set_product(product: Dict[str, Any]) -> bool:
    # Per riconoscere un set guardiamo il titolo/tipo del prodotto, non la
    # descrizione commerciale: una descrizione di un profumo può citare un set.
    fields = ("name", "title", "product_name", "category", "type", "product_type")
    text = norm(" ".join(str(product.get(field) or "") for field in fields))
    return any(_contains_term(text, marker) for marker in SET_PRODUCTS)


def _product_search_text(product: Dict[str, Any]) -> str:
    fields = (
        "name", "title", "product_name", "description",
        "category", "type", "product_type", "sub_category", "subcategory"
    )
    return norm(" ".join(str(product.get(field) or "") for field in fields))


def is_non_perfume(product: Dict[str, Any]) -> bool:
    if _is_set_product(product):
        return False
    text = _product_search_text(product)
    if not text:
        return True
    return any(_contains_term(text, phrase) for phrase in NON_PERFUME if norm(phrase))


def matches(product: Dict[str, Any], query: str) -> bool:
    item = normalize_product(product, query)
    name = norm(item.get("name", ""))
    brand = norm(item.get("brand", ""))
    query_normalized = norm(query)
    if not name or is_non_perfume(item):
        return False

    # Le ricerche di una linea devono restituire tutta la linea, anche quando
    # l'utente inserisce una variante specifica (es. "Le Beau Le Parfum").
    family = family_search_plan(query)
    if family:
        # Per le linee usiamo il nome della linea, non il campo "brand"
        # restituito dallo scraper: alcuni negozi lo omettono o lo scrivono
        # in modo diverso.
        if family is LINE_FAMILY_PLANS["le beau"]:
            return bool(re.search(r"\ble\s+beau\b", name))
        if family is LINE_FAMILY_PLANS["9 pm"]:
            return bool(re.search(r"(?:^|\s)9\s*pm(?:\s|$)", name))
        if family is LINE_FAMILY_PLANS["9 am"]:
            return bool(re.search(r"(?:^|\s)9\s*am(?:\s|$)", name))

    tokens = [token for token in query_normalized.split() if token not in IGNORED_WORDS]
    if not tokens:
        return False
    if not all(token in name for token in tokens):
        return False
    if _query_has_variant_marker(query):
        query_tokens = set(tokens)
        name_tokens = set(name.split())
        for marker in VARIANT_MARKERS:
            marker_tokens = set(norm(marker).split())
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
) -> List[str]:
    """Costruisce query generiche; nessun nome di profumo è hard-coded."""
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()
        value_norm = norm(value)
        if value_norm and value_norm not in {norm(x) for x in attempts}:
            attempts.append(value)

    add(raw)

    # Per le linee note facciamo anche le ricerche delle varianti della linea.
    # Il risultato finale viene comunque filtrato da matches(), quindi non
    # entrano prodotti di altre linee. Questo evita di perdere varianti che un
    # negozio non restituisce quando si cerca solo il nome della famiglia.
    family = family_search_plan(raw)
    if family:
        for term in family["terms"]:
            add(term)
        # Per una linea restiamo sulle query della linea: i fallback generici
        # consumano il limite di risultati dei negozi e fanno sparire varianti.
        return attempts[:10]

    # Un solo passaggio aggiuntivo sul brand scoperto permette di recuperare
    # varianti che il motore interno del negozio non mostra con la query esatta.
    for brand in discovered_brands or []:
        add(brand)
    for hint in catalog_hints or []:
        add(hint)
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
    return attempts[:12]


def run_store(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Ricerca iniziale + espansione generica per brand per le query di famiglia."""
    module = load_scraper(store)
    raw_query = str(query or "").strip()
    initial_results = module.search(raw_query) or []
    discovered_brands: List[str] = []
    brand_seen = set()
    for item in initial_results:
        if not isinstance(item, dict):
            continue
        brand = str(item.get("brand") or "").strip()
        if brand and norm(brand) not in brand_seen:
            brand_seen.add(norm(brand))
            discovered_brands.append(brand)
    for brand in _catalog_brand_candidates(raw_query):
        if norm(brand) not in brand_seen:
            brand_seen.add(norm(brand))
            discovered_brands.append(brand)

    attempts = build_search_attempts(store, raw_query, catalog_hints, discovered_brands)
    output: List[Dict[str, Any]] = []
    seen = set()
    pending = [attempt for attempt in attempts if norm(attempt) != norm(raw_query)]
    batches = [(raw_query, initial_results)]
    for attempt in pending:
        try:
            batches.append((attempt, module.search(attempt) or []))
        except Exception:
            continue

    for attempt, results in batches:
        for item in results:
            if not isinstance(item, dict):
                continue
            product = normalize_product({**item, "store": item.get("store") or store}, raw_query)
            key = (str(product.get("url", "")).lower(), norm(product.get("name", "")))
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


def sort_by_name(
    products: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Ordine alfabetico rigoroso sul nome normalizzato Brand - Nome."""
    return sorted(
        products,
        key=lambda product: (
            norm(product.get("display_name") or f"{product.get('brand', '')} {product.get('name', '')}"),
            norm(product.get("store", "")),
            str(product.get("url", "")).lower(),
        ),
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

    # Il catalogo locale fornisce il brand della famiglia.
    # Non interroghiamo Fragella durante /search: riduciamo chiamate e RAM.
    catalog_hints: List[str] = _catalog_brand_candidates(query)

    # NON 8 insieme: su Render Free abbiamo osservato exit 137.
    # Due worker riducono nettamente RAM e connessioni simultanee.
    executor = ThreadPoolExecutor(max_workers=2)
    futures = {
        executor.submit(run_store, store, query, catalog_hints): store
        for store in STORES
    }

    search_timeout = 50 if family_search_plan(query) else 28

    try:
        for future in as_completed(futures, timeout=search_timeout):
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

    normalized_results = [
        normalize_product(product, query)
        for product in all_results
    ]
    results = sort_by_name(unique_results(normalized_results))

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

        if any(_contains_term(name_n, phrase) for phrase in NON_PERFUME):
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
