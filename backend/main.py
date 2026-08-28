from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import traceback
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse
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

    # Uniforma le diverse grafie della numerazione Chanel e simili:
    # "N 19", "N° 19", "No. 19", "No 19" -> "no 19".
    # In questo modo la stessa famiglia non viene spezzata in gruppi
    # diversi solo per la nomenclatura usata dallo store.
    value = re.sub(r"\b(?:no|n)\s*(?=\d)", "no ", value)

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

# ============================================================
# REGISTRO GENERICO DELLE FAMIGLIE
# ============================================================
FAMILY_REGISTRY_FILENAME = "family_registry.json"
FAMILY_REGISTRY: Dict[str, Dict[str, Any]] = {}
FAMILY_ALIAS_TO_ID: Dict[str, str] = {}
FAMILY_VARIANT_ALIASES: Dict[str, str] = {}


def _family_registry_paths() -> List[Path]:
    base = Path(BASE_DIR).resolve()
    candidates = [
        base / FAMILY_REGISTRY_FILENAME,
        base.parent / FAMILY_REGISTRY_FILENAME,
        Path.cwd() / FAMILY_REGISTRY_FILENAME,
    ]
    unique = []
    seen = set()
    for candidate in candidates:
        if str(candidate) not in seen:
            seen.add(str(candidate))
            unique.append(candidate)
    return unique


def _load_family_registry() -> None:
    global FAMILY_REGISTRY, FAMILY_ALIAS_TO_ID, FAMILY_VARIANT_ALIASES

    payload = None
    for path in _family_registry_paths():
        try:
            with path.open("r", encoding="utf-8") as file:
                payload = json.load(file)
            break
        except (OSError, ValueError, TypeError):
            continue

    if not isinstance(payload, dict):
        return

    families = payload.get("families")
    if not isinstance(families, list):
        return

    for family in families:
        if not isinstance(family, dict):
            continue

        family_id = norm(family.get("family_id"))
        brand = str(family.get("brand") or "").strip()
        if not family_id or not brand:
            continue

        aliases = family.get("query_aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]

        variants = []
        for product in family.get("products") or []:
            if not isinstance(product, dict):
                continue

            canonical = str(product.get("canonical_name") or "").strip()
            if not canonical:
                continue

            if norm(canonical) not in {norm(v) for v in variants}:
                variants.append(canonical)

            product_aliases = product.get("aliases") or []
            if isinstance(product_aliases, str):
                product_aliases = [product_aliases]

            for alias in product_aliases:
                alias_text = str(alias or "").strip()
                if not alias_text:
                    continue
                FAMILY_VARIANT_ALIASES[norm(alias_text)] = canonical
                FAMILY_VARIANT_ALIASES[norm(f"{brand} {alias_text}")] = canonical

        FAMILY_REGISTRY[family_id] = {
            "family_id": family_id,
            "brand": brand,
            "query_aliases": [str(x).strip() for x in aliases if str(x).strip()],
            "canonical_variants": variants,
        }

        for alias in aliases:
            alias_text = str(alias or "").strip()
            if alias_text:
                FAMILY_ALIAS_TO_ID[norm(alias_text)] = family_id
                FAMILY_ALIAS_TO_ID[norm(f"{brand} {alias_text}")] = family_id


def _resolve_family(query: str) -> Optional[Dict[str, Any]]:
    query_n = norm(query)
    if not query_n:
        return None

    family_id = FAMILY_ALIAS_TO_ID.get(query_n)

    if not family_id:
        stripped = re.sub(
            r"\b(?:eau de parfum|eau de toilette|eau de cologne|"
            r"extrait(?: de parfum)?|edp|edt|edc|"
            r"pour homme|pour femme|for men|for women|for him|for her|"
            r"uomo|donna|men|women|man|woman|homme|femme)\b",
            " ",
            query_n,
        )
        stripped = re.sub(r"\s+", " ", stripped).strip()
        family_id = FAMILY_ALIAS_TO_ID.get(stripped)

    return FAMILY_REGISTRY.get(family_id) if family_id else None


def _registry_canonical_variant(brand: str, raw_name: str) -> str:
    for candidate in (norm(raw_name), norm(f"{brand} {raw_name}")):
        canonical = FAMILY_VARIANT_ALIASES.get(candidate)
        if canonical:
            return canonical
    return ""


def _family_variant_allowed(
    product: Dict[str, Any],
    family: Dict[str, Any],
) -> bool:
    product_brand = norm(product.get("brand") or "")
    family_brand = norm(family.get("brand") or "")

    if product_brand and family_brand and product_brand != family_brand:
        return False

    allowed = {
        norm(value)
        for value in family.get("canonical_variants") or []
    }

    canonical_name = norm(product.get("name") or "")
    if canonical_name in allowed:
        return True

    raw_name = str(
        product.get("title")
        or product.get("product_name")
        or product.get("source_name")
        or product.get("name")
        or ""
    ).strip()

    resolved = _registry_canonical_variant(
        str(product.get("brand") or ""),
        raw_name,
    )

    return bool(resolved and norm(resolved) in allowed)


_load_family_registry()



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
    canonical = (
        _registry_canonical_variant(brand, raw_name)
        or CATALOG_ALIASES.get(norm(raw_name))
        or CATALOG_ALIASES.get(norm(f"{brand} {raw_name}"))
    )
    name = canonical or raw_name
    if brand:
        name = re.sub(rf"^\s*{re.escape(brand)}\s*[-–—:]?\s*", "", name, flags=re.I).strip()

    # Se il catalogo fornisce una referenza canonica francese come
    # "Eros pour Femme ...", manteniamo "Femme" nel nome canonico.
    # Non va trasformato in "Donna", altrimenti perdiamo la corrispondenza
    # con la referenza del catalogo e con la query originale.
    if not (canonical and re.search(r"\bfemme\b|\bhomme\b", name, flags=re.I)):
        name = _move_gender_after_family(name, family_query)
    words = name.split()
    collapsed = []
    for word in words:
        if collapsed and norm(collapsed[-1]) == norm(word):
            continue
        collapsed.append(word)
    name = " ".join(collapsed)
    name = re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", name).strip()

    # Canonicalizza la nomenclatura numerica Chanel anche nel NOME VISIBILE,
    # non solo nella chiave di confronto. In questo modo "N 19" e "No. 19"
    # non vengono mostrati come due famiglie/categorie differenti.
    name = re.sub(r"\b(?:no\.?|n)\s*(\d+)\b", r"No. \1", name, flags=re.I)

    return name


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

def _query_concentration(value: Any) -> str:
    """
    Riconosce la concentrazione solo quando e' realmente indicata.

    Importante: EDT ed EDP sono referenze diverse. Non devono essere
    trattate come semplici parole ignorate durante il matching.
    """
    text = norm(value)
    if not text:
        return ""

    if re.search(r"\beau de parfum\b", text) or re.search(r"\bedp\b", text):
        return "edp"
    if re.search(r"\beau de toilette\b", text) or re.search(r"\bedt\b", text):
        return "edt"
    if re.search(r"\bextrait(?: de parfum)?\b", text):
        return "extrait"
    return ""


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


def matches(
    product: Dict[str, Any],
    query: str,
    family: Optional[Dict[str, Any]] = None,
) -> bool:
    item = normalize_product(product, query)
    name = norm(item.get("name", ""))
    query_normalized = norm(query)
    if not name or is_non_perfume(item):
        return False

    # Famiglia verificata = confine rigido dell'identità.
    # Il titolo del retailer non può creare appartenenza alla famiglia.
    if family is not None and not _family_variant_allowed(item, family):
        return False

    # Se la query specifica una concentrazione, la stessa concentrazione
    # deve essere presente nel nome del risultato.
    # Esempio: "Eros pour Femme Eau de Parfum" NON puo' accettare
    # "Eros pour Femme Eau de Toilette". Se la query non specifica
    # EDT/EDP, entrambe le referenze restano valide.
    query_concentration = _query_concentration(query)
    if query_concentration:
        name_concentration = _query_concentration(name)
        if name_concentration != query_concentration:
            return False

    # canonical_product_name() porta "femme/homme" in coda e li traduce
    # rispettivamente in "Donna/Uomo" per il nome visualizzato.
    # Per il matching conserviamo quindi anche i sinonimi originali,
    # altrimenti una query francese come "Eros pour Femme" non troverebbe
    # piu' la referenza corretta.
    matching_name = name
    if "donna" in name.split():
        matching_name += " femme women woman"
    if "uomo" in name.split():
        matching_name += " femme homme men man"
    matching_name = norm(matching_name)

    tokens = [token for token in query_normalized.split() if token not in IGNORED_WORDS]

    # Il brand puo' essere scritto nella query (es. "Versace Eros pour Femme").
    # Il brand viene gia' confrontato separatamente e non deve rendere falsa
    # una corrispondenza del nome prodotto.
    brand_tokens = set(norm(item.get("brand") or "").split())
    if brand_tokens:
        tokens = [token for token in tokens if token not in brand_tokens]

    if not tokens:
        return False
    # La query deve comparire realmente nel nome: una famiglia non deve
    # trasformarsi automaticamente in una variante specifica.
    if not all(token in matching_name for token in tokens):
        return False
    if _query_has_variant_marker(query):
        query_tokens = set(tokens)
        name_tokens = set(name.split())
        for marker in VARIANT_MARKERS:
            marker_norm = norm(marker)
            # "parfum", "extrait", "edp" ed "edt" fanno parte della
            # concentrazione e vengono gestiti separatamente sopra.
            if marker_norm in {
                "parfum", "extrait", "edp", "edt",
                "eau de parfum", "eau de toilette",
            }:
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
    """Costruisce query generiche; nessun nome di profumo è hard-coded."""
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()
        value_norm = norm(value)
        if value_norm and value_norm not in {norm(x) for x in attempts}:
            attempts.append(value)

    # Prima la query esatta.
    add(raw)

    # Se il catalogo conosce già le referenze della famiglia, usiamo quelle
    # come query mirate. Questo evita di lanciare 10-20 ricerche sullo stesso
    # negozio e, soprattutto, permette di recuperare separatamente EDT/EDP.
    if family_candidates:
        for family_name in family_candidates:
            add(family_name)
        for hint in catalog_hints or []:
            add(hint)
        return attempts[:8]

    # Fallback per query che non hanno corrispondenze nel catalogo.
    for brand in discovered_brands or []:
        add(brand)
        add(f"{brand} {raw}")
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

    # Anche nel fallback non superiamo 8 tentativi per negozio.
    return attempts[:8]


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

    # Se abbiamo già le referenze della famiglia dal catalogo, non serve
    # fare una seconda espansione per brand: aggiungere altre query qui
    # moltiplica inutilmente i tempi dello scraper.
    if not family_candidates:
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
    family = _resolve_family(raw_query)
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
            if matches(product, raw_query, family=family):
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

# Ricerca progressiva usata dal frontend: ogni store viene eseguito in
# parallelo e /search-status restituisce subito i risultati degli store
# già terminati, senza aspettare quelli più lenti.
SEARCH_JOBS: Dict[str, Dict[str, Any]] = {}
SEARCH_JOBS_LOCK = threading.Lock()
SEARCH_JOB_TIMEOUT = 60
SEARCH_JOB_TTL = 300


def _cleanup_search_jobs() -> None:
    now = datetime.now(timezone.utc).timestamp()
    stale: List[Dict[str, Any]] = []
    with SEARCH_JOBS_LOCK:
        for job_id, job in list(SEARCH_JOBS.items()):
            if job.get("completed") and now - float(job.get("finished_at") or now) > SEARCH_JOB_TTL:
                stale.append(SEARCH_JOBS.pop(job_id))
    for job in stale:
        executor = job.get("executor")
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)


def _search_job_payload(job: Dict[str, Any]) -> Dict[str, Any]:
    all_results: List[Dict[str, Any]] = list(job.get("all_results") or [])
    errors: Dict[str, str] = dict(job.get("errors") or {})

    for store, future in job["futures"].items():
        if not future.done():
            continue
        if store in job["collected"]:
            continue
        job["collected"].add(store)
        try:
            new_results = future.result() or []
            all_results.extend(new_results)
            job["all_results"].extend(new_results)
        except Exception as error:
            errors[store] = f"{type(error).__name__}: {error}"
            traceback.print_exc()

    query = job["query"]
    normalized_results = [
        normalize_product(product, query)
        for product in all_results
    ]
    results = sort_by_name(unique_results(normalized_results))

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "comparisons": [],
        "errors": errors,
        "completed": bool(job.get("completed")),
    }


@app.get("/search-start")
def search_start(q: str):
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query vuota")

    _cleanup_search_jobs()

    catalog_hints: List[str] = _catalog_brand_candidates(query)
    family_candidates: List[str] = _catalog_family_candidates(query)
    executor = ThreadPoolExecutor(max_workers=len(STORES))
    job_id = uuid.uuid4().hex
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
    job = {
        "query": query,
        "created_at": datetime.now(timezone.utc).timestamp(),
        "finished_at": None,
        "executor": executor,
        "futures": {store: future for future, store in futures.items()},
        "collected": set(),
        "all_results": [],
        "errors": {},
        "completed": False,
    }
    with SEARCH_JOBS_LOCK:
        SEARCH_JOBS[job_id] = job

    return {"job_id": job_id, "query": query}


@app.get("/search-status")
def search_status(job_id: str):
    _cleanup_search_jobs()
    with SEARCH_JOBS_LOCK:
        job = SEARCH_JOBS.get(str(job_id or ""))

    if job is None:
        raise HTTPException(status_code=404, detail="Ricerca non trovata o scaduta")

    now = datetime.now(timezone.utc).timestamp()
    all_done = all(future.done() for future in job["futures"].values())
    timed_out = now - float(job["created_at"]) >= SEARCH_JOB_TIMEOUT

    if (all_done or timed_out) and not job["completed"]:
        if timed_out and not all_done:
            for store, future in job["futures"].items():
                if not future.done():
                    if future.cancel():
                        job["errors"][store] = "Non eseguito: limite tempo ricerca"
                    else:
                        job["errors"][store] = "Timeout: negozio troppo lento"
        job["completed"] = True
        job["finished_at"] = now
        job["executor"].shutdown(wait=False, cancel_futures=True)

    payload = _search_job_payload(job)
    return payload


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

    # Tutti gli store vengono avviati in parallelo: un negozio lento non deve
    # tenere in coda gli altri. Il limite globale evita che una singola ricerca
    # resti bloccata indefinitamente.
    executor = ThreadPoolExecutor(max_workers=len(STORES))
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
                all_results.extend(future.result())
            except Exception as error:
                errors[store] = f"{type(error).__name__}: {error}"
                traceback.print_exc()
    except TimeoutError:
        # Restituisce comunque tutti i risultati già completati.
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
# API - DIAGNOSTICA ESCLUSIVA DELOOX
# ============================================================

@app.get("/diagnostic-deloox")
def diagnostic_deloox():
    """
    Diagnostica esclusivamente il caricamento del modulo Deloox.
    NON esegue ricerche, NON chiama Deloox.be e NON passa dal matcher.
    Serve a verificare esattamente quale scraper sta caricando Railway.
    """
    store = "deloox"
    report = {
        "store": store,
        "requested_module": "scrapers.deloox.scraper",
        "import_ok": False,
        "module_name": None,
        "module_file": None,
        "module_package": None,
        "base_url": None,
        "has_search": False,
        "has_scrape": False,
        "has_discover": False,
        "has_candidate_product_urls": False,
        "has_product": False,
        "error": None,
    }

    try:
        module = load_scraper(store)
        report["import_ok"] = True
        report["module_name"] = getattr(module, "__name__", None)
        report["module_file"] = getattr(module, "__file__", None)
        report["module_package"] = getattr(module, "__package__", None)
        report["base_url"] = getattr(module, "BASE_URL", None)
        report["has_search"] = callable(getattr(module, "search", None))
        report["has_scrape"] = callable(getattr(module, "scrape", None))
        report["has_discover"] = callable(getattr(module, "_discover", None))
        report["has_candidate_product_urls"] = callable(
            getattr(module, "_candidate_product_urls", None)
        )
        report["has_product"] = callable(getattr(module, "_product", None))
    except Exception as error:
        report["error"] = f"{type(error).__name__}: {error}"
        traceback.print_exc()

    return report


# ============================================================
# API - DIAGNOSTICA PROFONDA ESCLUSIVA DELOOX
# ============================================================

@app.get("/diagnostic-deloox-search")
def diagnostic_deloox_search(q: str):
    """
    Diagnostica profonda esclusivamente Deloox.

    Chiama direttamente diagnose_search() del vero scraper Deloox,
    usando la stessa requests.Session del modulo, senza passare
    dalla normale pipeline /search e senza applicare il matcher.
    """
    query = str(q or "").strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Parametro q mancante",
        )

    try:
        module = load_scraper("deloox")
        diagnose_fn = getattr(module, "diagnose_search", None)

        if not callable(diagnose_fn):
            raise RuntimeError(
                "Deloox scraper non espone diagnose_search()"
            )

        requests_module = getattr(module, "requests", None)

        if requests_module is None:
            raise RuntimeError(
                "Deloox scraper non espone il modulo requests"
            )

        session = requests_module.Session()

        try:
            diagnostic = diagnose_fn(
                session,
                query,
            )
        finally:
            session.close()

        return {
            "ok": True,
            "store": "deloox",
            "query": query,
            "diagnostic": diagnostic,
        }

    except HTTPException:
        raise
    except Exception as error:
        traceback.print_exc()
        return {
            "ok": False,
            "store": "deloox",
            "query": query,
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }


# ============================================================
# API - DIAGNOSTICA HOMEPAGE REALE DELOOX
# ============================================================

class _DelooxHomepageParser(HTMLParser):
    """Parser HTML leggero usato solo dal diagnostico Deloox."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: List[str] = []
        self.forms: List[Dict[str, Any]] = []
        self.scripts: List[Dict[str, Any]] = []
        self.meta: List[Dict[str, str]] = []
        self.title_parts: List[str] = []
        self._in_title = False
        self._current_form: Optional[Dict[str, Any]] = None
        self._current_script: Optional[Dict[str, Any]] = None

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        tag = tag.lower()

        if tag == "title":
            self._in_title = True
        elif tag == "a" and data.get("href"):
            self.links.append(data["href"].strip())
        elif tag == "form":
            self._current_form = {
                "action": data.get("action", ""),
                "method": data.get("method", "get").lower(),
                "inputs": [],
            }
            self.forms.append(self._current_form)
        elif tag in {"input", "select", "textarea", "button"} and self._current_form is not None:
            self._current_form["inputs"].append({
                "tag": tag,
                "name": data.get("name", ""),
                "type": data.get("type", ""),
                "value": data.get("value", ""),
                "placeholder": data.get("placeholder", ""),
            })
        elif tag == "script":
            self._current_script = {
                "src": data.get("src", ""),
                "type": data.get("type", ""),
                "text": [],
            }
            self.scripts.append(self._current_script)
        elif tag == "meta":
            key = data.get("name") or data.get("property") or data.get("http-equiv") or ""
            value = data.get("content", "")
            if key or value:
                self.meta.append({"key": key, "content": value})

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "title":
            self._in_title = False
        elif tag == "form":
            self._current_form = None
        elif tag == "script":
            self._current_script = None

    def handle_data(self, data):
        if self._in_title:
            self.title_parts.append(data)
        if self._current_script is not None:
            self._current_script["text"].append(data)


@app.get("/diagnostic-deloox-homepage")
def diagnostic_deloox_homepage():
    """
    Diagnostica esclusivamente la homepage REALE di Deloox.

    Non esegue il normale search(), non usa il matcher e non assume
    categorie o URL prodotto predefiniti. Parte da BASE_URL del vero
    scraper caricato da Railway e analizza ciò che Deloox espone oggi.
    """
    try:
        module = load_scraper("deloox")
        base_url = str(getattr(module, "BASE_URL", "") or "").strip()
        if not base_url:
            raise RuntimeError("Deloox scraper non espone BASE_URL")

        requests_module = getattr(module, "requests", None)
        if requests_module is None:
            raise RuntimeError("Deloox scraper non espone il modulo requests")

        session = requests_module.Session()
        try:
            response = session.get(
                base_url,
                timeout=30,
                allow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,nl;q=0.8,fr;q=0.7",
                },
            )

            html = response.text or ""
            parser = _DelooxHomepageParser()
            parser.feed(html)

            base_host = urlparse(response.url).netloc.lower()
            resolved_links: List[Dict[str, str]] = []
            seen = set()

            for raw_href in parser.links:
                if not raw_href or raw_href.startswith(("#", "javascript:", "mailto:", "tel:")):
                    continue
                absolute = urljoin(response.url, raw_href)
                parsed = urlparse(absolute)
                if parsed.scheme not in {"http", "https"}:
                    continue
                key = absolute
                if key in seen:
                    continue
                seen.add(key)
                resolved_links.append({
                    "href": raw_href,
                    "url": absolute,
                    "path": parsed.path,
                    "query": parsed.query,
                    "same_host": parsed.netloc.lower() == base_host,
                })

            same_host_links = [x for x in resolved_links if x["same_host"]]
            search_links = [
                x for x in same_host_links
                if any(token in (x["url"] + " " + x["path"] + " " + x["query"]).lower()
                       for token in ("search", "zoek", "query", "q="))
            ]
            category_links = [
                x for x in same_host_links
                if any(token in x["path"].lower()
                       for token in ("category", "categorie", "parfum", "fragrance", "heren", "dames", "men", "women"))
            ]
            product_links = [
                x for x in same_host_links
                if any(token in x["path"].lower()
                       for token in ("product", "parfum", "perfume"))
            ]

            script_report = []
            clue_patterns = (
                "api", "graphql", "/search", "search?", "algolia", "elastic", "product",
                "autocomplete", "suggest", "__next_data__", "application/ld+json"
            )
            for script in parser.scripts:
                text = "".join(script.get("text", []))
                lowered = text.lower()
                clues = [pattern for pattern in clue_patterns if pattern in lowered]
                src = script.get("src", "")
                if src or clues:
                    script_report.append({
                        "src": urljoin(response.url, src) if src else "",
                        "type": script.get("type", ""),
                        "length": len(text),
                        "clues": clues,
                        "snippet": text[:1200] if clues else "",
                    })

            meta_report = [m for m in parser.meta if m["key"] and m["content"]]

            return {
                "ok": True,
                "store": "deloox",
                "base_url_from_scraper": base_url,
                "request": {
                    "url": base_url,
                    "method": "GET",
                },
                "response": {
                    "status": response.status_code,
                    "final_url": response.url,
                    "content_type": response.headers.get("Content-Type", ""),
                    "content_length_bytes": len(response.content or b""),
                    "history": [
                        {"status": r.status_code, "url": r.url, "location": r.headers.get("Location", "")}
                        for r in response.history
                    ],
                },
                "html": {
                    "title": " ".join(" ".join(parser.title_parts).split()),
                    "forms": parser.forms,
                    "meta": meta_report[:100],
                    "total_links": len(resolved_links),
                    "same_host_links": len(same_host_links),
                },
                "discovery": {
                    "search_links": search_links[:100],
                    "category_links": category_links[:200],
                    "product_like_links": product_links[:200],
                },
                "scripts": script_report[:100],
                "raw_html_head": html[:5000],
            }
        finally:
            session.close()

    except Exception as error:
        traceback.print_exc()
        return {
            "ok": False,
            "store": "deloox",
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
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
