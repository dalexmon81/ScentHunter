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

CATALOG_FILENAME = "SCENTHUNTER CATALOGO CORRETTO.json"

VARIANT_MARKERS = {
    "pour femme", "pour homme", "femme", "homme",
    "uomo", "donna", "men", "women", "man", "woman",
    "flame", "energy", "night", "night out",
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

NON_RETAIL_PERFUME = {
    "tester",
    "testeur",
    "sample",
    "échantillon",
    "echantillon",
    "mystery box",
    "mysterybox",
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

    # Never collapse a variant-specific product to a shorter base-catalog
    # name when the current search explicitly contains variant markers.
    # Example: a catalog alias may map "Family X Limited Edition" to
    # "Family X"; for a search for "Family X Limited Edition" that would
    # destroy the very identity we need to match.
    family_tokens = {
        token
        for token in norm(family_query).split()
        if token not in IGNORED_WORDS
    }
    canonical_tokens = set(norm(canonical or "").split())
    raw_tokens = set(norm(raw_name).split())
    if family_tokens and not family_tokens.issubset(canonical_tokens):
        name = raw_name
    else:
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


def _set_primary_text(product: Dict[str, Any]) -> str:
    """Raccoglie solo i campi che descrivono l'identità del set."""
    fields = ("name", "title", "product_name")
    return " ".join(
        str(product.get(field) or "").strip()
        for field in fields
        if str(product.get(field) or "").strip()
    )


_SET_COMPONENT_SEPARATORS = re.compile(
    r"\s*(?:\+|&|,|;|\|)\s*|\s+(?:and|avec|mit|und|con|et)\s+",
    re.I,
)

_SET_GENERIC_COMPONENT_WORDS = {
    "gift", "set", "regalo", "coffret", "bundle", "travel",
    "discovery", "kit", "perfume", "parfum", "fragrance",
    "eau", "de", "edp", "edt", "extrait", "spray",
    "ml", "cl", "oz", "pack", "pcs", "piece", "pieces", "x",
    "for", "men", "women", "man", "woman", "homme", "femme",
    "uomo", "donna",
}


def _meaningful_set_component(text: str) -> List[str]:
    """Restituisce i token che possono rappresentare un articolo distinto."""
    text = norm(text)
    if not text:
        return []

    tokens: List[str] = []
    for token in text.split():
        if token in _SET_GENERIC_COMPONENT_WORDS:
            continue
        if re.fullmatch(r"\d+(?:[.,]\d+)?", token):
            continue
        if re.fullmatch(r"\d+(?:[.,]\d+)?(?:ml|cl|oz)", token):
            continue
        tokens.append(token)
    return tokens


def _set_contains_other_product(product: Dict[str, Any], query: str) -> bool:
    """
    Un set è fuori identità quando il titolo mostra più articoli distinti
    separati esplicitamente e la query identifica solo uno dei componenti.

    Non conosce nomi di profumi o negozi: usa esclusivamente la struttura
    generica del titolo del set.
    """
    primary = _set_primary_text(product)
    query_tokens = [
        token
        for token in norm(query).split()
        if token not in IGNORED_WORDS
    ]

    if not primary or not query_tokens:
        return False

    primary_normalized = norm(primary)
    if not all(token in primary_normalized for token in query_tokens):
        return False

    parts = [
        part.strip()
        for part in _SET_COMPONENT_SEPARATORS.split(primary)
        if part.strip()
    ]

    meaningful_parts = [
        _meaningful_set_component(part)
        for part in parts
    ]
    meaningful_parts = [tokens for tokens in meaningful_parts if tokens]

    if len(meaningful_parts) < 2:
        return False

    def part_matches_query(tokens: List[str]) -> bool:
        token_set = set(tokens)
        return all(token in token_set for token in query_tokens)

    matching_parts = [tokens for tokens in meaningful_parts if part_matches_query(tokens)]
    if not matching_parts:
        return False

    # Se un'altra componente significativa non contiene la query, il set è
    # un combo di più prodotti e non un'offerta dello stesso prodotto cercato.
    return any(not part_matches_query(tokens) for tokens in meaningful_parts)


def _is_set_product(product: Dict[str, Any]) -> bool:
    # Per riconoscere un set guardiamo il titolo/tipo del prodotto, non la
    # descrizione commerciale: una descrizione di un profumo può citare un set.
    fields = ("name", "title", "product_name", "category", "type", "product_type")
    text = norm(" ".join(str(product.get(field) or "") for field in fields))
    return any(_contains_term(text, marker) for marker in SET_PRODUCTS)


def _product_search_text(product: Dict[str, Any]) -> str:
    # The product identity/type fields are authoritative. Descriptions often
    # mention unrelated cosmetics (for example a gift-set description can
    # mention shower gel), so they must not decide the product category.
    fields = (
        "name", "title", "product_name",
        "category", "type", "product_type",
        "sub_category", "subcategory",
    )
    return norm(" ".join(str(product.get(field) or "") for field in fields))


def is_non_perfume(product: Dict[str, Any], query: str = "") -> bool:
    text = _product_search_text(product)
    if not text:
        return True

    # Testers, samples and mystery-box products are not normal perfume offers.
    if any(_contains_term(text, phrase) for phrase in NON_RETAIL_PERFUME):
        return True

    # Cosmetics, body/hair products and other non-fragrance merchandise are
    # always rejected, including when they are packaged as a gift set.
    if any(
        _contains_term(text, phrase)
        for phrase in NON_PERFUME
        if norm(phrase)
    ):
        return True

    # A perfume set is allowed, but a multi-product combo must not be attached
    # to the identity of only one of its components.
    if _is_set_product(product):
        if _set_contains_other_product(product, query):
            return True
        return False

    return False


def matches(product: Dict[str, Any], query: str) -> bool:
    item = normalize_product(product, query)
    name = norm(item.get("name", ""))
    query_normalized = norm(query)
    if not name or is_non_perfume(item, query):
        return False
    tokens = [token for token in query_normalized.split() if token not in IGNORED_WORDS]
    if not tokens:
        return False
    # La query deve comparire realmente nel nome.
    if not all(token in name for token in tokens):
        return False

    # Una ricerca generica della famiglia deve restituire il prodotto base,
    # non una variante specifica. Lo stesso controllo vale per una ricerca
    # già specifica: in quel caso sono ammessi solo i marcatori dichiarati
    # nella query.
    query_tokens = set(tokens)
    name_tokens = set(name.split())

    for marker in VARIANT_MARKERS:
        marker_tokens = set(norm(marker).split())
        if not marker_tokens:
            continue
        if marker_tokens.issubset(name_tokens) and not marker_tokens.issubset(query_tokens):
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
    # Un solo passaggio aggiuntivo sul brand scoperto permette di recuperare
    # varianti che il motore interno del negozio non mostra con la query esatta.
    for brand in discovered_brands or []:
        add(brand)
        # Query composta: alcuni negozi restituiscono più varianti quando
        # ricevono brand + famiglia invece del solo brand.
        add(f"{brand} {raw}")
    for hint in catalog_hints or []:
        add(hint)
    # Ogni variante del catalogo diventa una query autonoma dello scraper.
    # Non c'è alcun elenco manuale di Eros/9 PM/Born in Roma.
    for family_name in family_candidates or []:
        add(family_name)
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
    return attempts[:20]


def run_store(
    store: str,
    query: str,
    catalog_hints: Optional[List[str]] = None,
    family_candidates: Optional[List[str]] = None,
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

    attempts = build_search_attempts(
        store,
        raw_query,
        catalog_hints,
        discovered_brands,
        family_candidates,
    )
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

            # Never expose a price as an active offer when the scraper has
            # explicitly established that the product is out of stock.
            offer = product.get("offer")
            if isinstance(offer, dict) and offer.get("availability") == "out_of_stock":
                offer["price"] = None
                product["offer"] = offer
            if product.get("available") is False and "offer" in product:
                if isinstance(product["offer"], dict):
                    product["offer"]["price"] = None
                product["price"] = ""

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

    # Il catalogo fornisce tutte le denominazioni della famiglia.
    # Queste query vengono passate agli scraper una per una.
    catalog_hints: List[str] = _catalog_brand_candidates(query)
    family_candidates: List[str] = _catalog_family_candidates(query)

    # NON 8 insieme: su Render Free abbiamo osservato exit 137.
    # Due worker riducono nettamente RAM e connessioni simultanee.
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
        "limit": max(1, min(int(limit), 50)),
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
