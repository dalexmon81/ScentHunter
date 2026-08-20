from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
from html import unescape
import os
import re
import traceback
import unicodedata
from concurrent.futures import ThreadPoolExecutor, TimeoutError, wait
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

VARIANTS = {
    "pour femme", "night out", "rebel", "elixir", "intense",
    "extreme", "limited edition", "collector edition", "collector's edition",
}

NON_PERFUME_MARKERS = {
    "tester", "testeur", "testing", "sample", "échantillon", "echantillon",
    "mystery box", "mysterybox",
    "shampoo", "shampoing", "shampooing", "conditioner", "apres shampooing",
    "hair mask", "hair care", "gel douche", "shower gel", "body wash",
    "body lotion", "lotion corps", "body cream", "body creme", "body butter",
    "hand cream", "hand creme", "handcreme", "face cream", "face creme",
    "facial cream", "moisturizer", "moisturiser", "creme visage",
    "serum", "sérum", "serum visage",
    "deodorant", "déodorant", "deo spray", "deodorant spray",
    "after shave", "aftershave", "baume apres rasage", "after shave balm",
    "lipstick", "rouge a levres", "makeup", "maquillage", "foundation",
    "concealer", "mascara", "eyeliner", "liquid blush", "blush liquide",
    "blush makeup", "blush maquillage", "bronzer", "highlighter",
    "nail polish", "vernis", "cosmetic", "cosmetique", "cosmetics",
    "cosmétiques", "skincare", "skin care",
}

PERFUME_SET_MARKERS = {
    "gift set", "set regalo", "coffret", "bundle", "travel set",
    "discovery set", "fragrance set", "perfume set", "parfum set",
}

PERFUME_TYPE_MARKERS = {
    "parfum", "perfume", "fragrance", "eau de parfum", "eau de toilette",
    "eau de cologne", "extrait", "edp", "edt", "edc", "cologne",
}

IGNORED_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "ml", "for", "by",
}


def norm(value: Any) -> str:
    value = str(value or "").lower().strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
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


def _extract_size_ml(text: Any) -> Optional[float]:
    """Estrae una misura SOLO quando è dichiarata con ml o cl."""
    text = str(text or "")
    match = re.search(r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl)\b", text, re.I)
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    if match.group(2).lower() == "cl":
        value *= 10.0
    return value


def _product_size_ml(product: Dict[str, Any]) -> Optional[float]:
    text = " ".join(
        str(product.get(key) or "")
        for key in ("name", "title", "product_name", "size_ml", "size")
    )
    return _extract_size_ml(text)


def _price_from_structured_html(html: str, target_size_ml: Optional[float] = None) -> Optional[float]:
    """Trova il prezzo della confezione corretta, non un prezzo aggregato o di un altro formato."""
    html = unescape(html or "")
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )

    candidates = []

    def offer_size(offer: Dict[str, Any], parent: Dict[str, Any]) -> Optional[float]:
        parts = []
        for key in ("name", "description", "sku", "url", "itemCondition"):
            parts.append(str(offer.get(key) or ""))
        for key in ("name", "description", "sku", "url"):
            parts.append(str(parent.get(key) or ""))
        return _extract_size_ml(" ".join(parts))

    def walk(value):
        if isinstance(value, dict):
            offers = value.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        price = price_num(offer.get("price"))
                        if price is not None:
                            candidates.append((offer_size(offer, value), price))
            for child in value.values():
                if isinstance(child, (dict, list)):
                    yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                if isinstance(child, (dict, list)):
                    yield from walk(child)

    for raw in scripts:
        try:
            payload = json.loads(raw.strip())
        except Exception:
            continue
        list(walk(payload))

    if not candidates:
        patterns = [
            r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([^"\']+)',
            r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)',
        ]
        for pattern in patterns:
            match = re.search(pattern, html, re.I)
            if match:
                return price_num(match.group(1))
        return None

    if target_size_ml is not None:
        exact = [price for size, price in candidates if size is not None and abs(size-target_size_ml) < 0.01]
        if exact:
            return exact[0]
        # Se la pagina espone più formati ma non riusciamo a collegare il prezzo al formato richiesto,
        # NON prendiamo arbitrariamente il primo prezzo: sarebbe proprio il tipo di errore che vogliamo evitare.
        known_sizes = {round(size, 2) for size, _ in candidates if size is not None}
        if len(known_sizes) > 1:
            return None

    return candidates[0][1]


# ============================================================
# DISPONIBILITÀ GENERALE SENTEHUNTER
# ============================================================
# Regola unica per tutti i negozi:
# - se uno scraper dichiara esplicitamente OUT OF STOCK, lo manteniamo;
# - se la pagina prodotto conferma OUT OF STOCK, lo marchiamo centralmente;
# - se la pagina conferma IN STOCK, lo marchiamo come disponibile;
# - se non riusciamo a determinare lo stock, NON eliminiamo mai il prodotto.
# In questo modo lo stock è normalizzato nel backend e non dipende da
# correzioni specifiche per singolo profumo o singolo negozio.

_STOCK_OOS_MARKERS = (
    "out of stock",
    "sold out",
    "unavailable",
    "not available",
    "currently unavailable",
    "out-of-stock",
    "this product is no longer available",
    "this product is no longer available for purchase",
    "product is no longer available",
    "no longer available",
    "rupture de stock",
    "en rupture",
    "épuisé",
    "indisponible",
    "actuellement indisponible",
    "produit indisponible",
    "non disponible",
    "non-disponible",
    "ce produit n'est plus disponible",
    "ce produit n’est plus disponible",
    "ce produit n'est plus disponible à la vente",
    "ce produit n’est plus disponible à la vente",
    "esaurito",
    "non disponibile",
    "questo prodotto non è più disponibile",
    "questo prodotto non e piu disponibile",
    "questo prodotto non è più disponibile per l'acquisto",
    "questo prodotto non e piu disponibile per l'acquisto",
    "nicht auf lager",
    "ausverkauft",
    "nicht verfügbar",
    "dieses produkt ist nicht mehr verfügbar",
    "dieses produkt ist nicht mehr verfugbar",
    "niet beschikbaar",
    "dit product is niet meer beschikbaar",
)

_STOCK_IN_MARKERS = (
    "in stock",
    "en stock",
    "disponible",
    "disponibilità immediata",
    "sofort lieferbar",
    "auf lager",
)


def _stock_value_is_oos(value: Any) -> bool:
    if value is False:
        return True
    s = norm(value).replace(" ", "_")
    return s in {
        "out_of_stock", "outofstock", "sold_out", "soldout",
        "unavailable", "not_available", "notavailable",
        "rupture_de_stock", "en_rupture", "epuise",
        "indisponible", "non_disponible", "non_disponible_online",
        "esaurito", "nicht_auf_lager", "ausverkauft",
        "nicht_verfugbar",
    }


def _stock_value_is_in(value: Any) -> bool:
    if value is True:
        return True
    s = norm(value).replace(" ", "_")
    return s in {
        "in_stock", "instock", "available", "in_stock_online",
        "en_stock", "disponible", "auf_lager", "sofort_lieferbar",
    }


def _structured_stock_from_html(html: str, target_size_ml: Optional[float] = None) -> Optional[bool]:
    """Legge JSON-LD e, quando possibile, verifica lo stock del formato richiesto."""
    html = unescape(html or "")
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )

    candidates = []

    def offer_size(offer: Dict[str, Any], parent: Dict[str, Any]) -> Optional[float]:
        parts=[]
        for key in ("name", "description", "sku", "url"):
            parts.append(str(offer.get(key) or ""))
        for key in ("name", "description", "sku", "url"):
            parts.append(str(parent.get(key) or ""))
        return _extract_size_ml(" ".join(parts))

    def walk(value):
        if isinstance(value, dict):
            offers=value.get("offers")
            if isinstance(offers, dict):
                offers=[offers]
            if isinstance(offers, list):
                for offer in offers:
                    if not isinstance(offer, dict):
                        continue
                    availability=str(offer.get("availability") or value.get("availability") or "").lower()
                    if availability:
                        candidates.append((offer_size(offer,value),availability))
            direct=str(value.get("availability") or "").lower()
            if direct and not offers:
                candidates.append((_extract_size_ml(" ".join(str(value.get(k) or "") for k in ("name","description","sku","url"))),direct))
            for child in value.values():
                if isinstance(child,(dict,list)):
                    yield from walk(child)
        elif isinstance(value,list):
            for child in value:
                if isinstance(child,(dict,list)):
                    yield from walk(child)

    for raw in scripts:
        try:
            payload=json.loads(raw.strip())
        except Exception:
            continue
        list(walk(payload))

    if not candidates:
        return None

    def status(value):
        s=str(value).lower()
        if any(x in s for x in ("outofstock","out_of_stock","soldout","sold_out","unavailable","discontinued")):
            return False
        if any(x in s for x in ("instock","in_stock","limitedavailability","preorder","backorder")):
            return True
        return None

    if target_size_ml is not None:
        matching=[status(a) for size,a in candidates if size is not None and abs(size-target_size_ml)<0.01]
        if matching:
            if False in matching:
                return False
            if True in matching:
                return True
            return None
        known_sizes={round(size,2) for size,_ in candidates if size is not None}
        if len(known_sizes)>1:
            return None

    states=[status(a) for _,a in candidates]
    if False in states and True not in states:
        return False
    if True in states and False not in states:
        return True
    if False in states and True in states:
        return None
    return None


def _stock_from_product_page(url: str, target_size_ml: Optional[float] = None) -> Optional[bool]:
    """
    Controllo generico della pagina prodotto.

    Restituisce:
      False = certamente OUT OF STOCK
      True  = certamente disponibile
      None  = informazione non determinabile

    Importante: None NON significa out of stock e non causa mai lo scarto
    del prodotto.
    """
    url = str(url or "").strip()
    if not url or not re.match(r"^https?://", url, re.I):
        return None

    try:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml",
                "User-Agent": "Mozilla/5.0 (compatible; ScentHunter/1.0)",
            },
        )
        with urlopen(request, timeout=3.5) as response:
            html = response.read().decode("utf-8", errors="ignore")
    except Exception:
        return None

    structured = _structured_stock_from_html(html, target_size_ml)
    if structured is not None:
        return structured

    page = unescape(html)
    visible = re.sub(r"<script[^>]*>.*?</script>", " ", page, flags=re.I | re.S)
    visible = re.sub(r"<style[^>]*>.*?</style>", " ", visible, flags=re.I | re.S)
    visible = re.sub(r"<[^>]+>", " ", visible)
    visible = re.sub(r"\s+", " ", visible).lower()

    # Prima i controlli di acquisto: sono più affidabili del testo generico.
    button_chunks = re.findall(
        r"<(?:button|input)[^>]*?(?:>.*?</button>|/?>)",
        page,
        flags=re.I | re.S,
    )
    button_text = " ".join(button_chunks).lower()
    if any(marker in button_text for marker in _STOCK_OOS_MARKERS):
        return False
    if any(marker in button_text for marker in _STOCK_IN_MARKERS):
        return True

    # Poi testo visibile della pagina. Un marker OOS esplicito prevale.
    if any(marker in visible for marker in _STOCK_OOS_MARKERS):
        return False
    if any(marker in visible for marker in _STOCK_IN_MARKERS):
        return True

    return None


def normalize_stock(product: Dict[str, Any], cache: Optional[Dict[str, Optional[bool]]] = None) -> Dict[str, Any]:
    """Applica la regola stock unica a un'offerta di qualunque negozio."""
    item = dict(product)

    # 1) Informazioni esplicite già fornite dallo scraper.
    fields = (
        "availability", "stock", "stock_status", "status",
        "availability_status", "availabilityStatus", "stockStatus",
        "in_stock", "inStock",
    )
    explicit_oos = any(_stock_value_is_oos(item.get(field)) for field in fields)
    explicit_in = any(_stock_value_is_in(item.get(field)) for field in fields)

    if item.get("available") is False:
        explicit_oos = True
    if item.get("available") is True:
        explicit_in = True

    if explicit_oos:
        item["available"] = False
        item["availability"] = "out_of_stock"
        item["stock_status"] = "out_of_stock"
        item["price"] = "Out of stock"
        item.pop("price_value", None)
        return item

    # 2) Se lo scraper ha già dichiarato IN STOCK, non facciamo una seconda
    #    richiesta alla pagina: evita timeout e perdita casuale dei negozi.
    if explicit_in:
        item["available"] = True
        item["availability"] = "in_stock"
        item["stock_status"] = "in_stock"
        return item

    # 3) Se lo stock è realmente sconosciuto, verifichiamo la pagina reale.
    #    Il risultato sconosciuto NON elimina mai il prodotto.
    url = str(item.get("url") or "").strip()
    page_stock = None
    if url:
        if cache is not None and url in cache:
            page_stock = cache[url]
        else:
            page_stock = _stock_from_product_page(url, _product_size_ml(item))
            if cache is not None:
                cache[url] = page_stock

    if page_stock is False:
        item["available"] = False
        item["availability"] = "out_of_stock"
        item["stock_status"] = "out_of_stock"
        item["price"] = "Out of stock"
        item.pop("price_value", None)
        return item

    if page_stock is True:
        item["available"] = True
        item["availability"] = "in_stock"
        item["stock_status"] = "in_stock"
        return item

    # Una dichiarazione esplicita del singolo scraper vale solo se la pagina
    # reale non ha dato una risposta contraria.
    if explicit_in:
        item["available"] = True
        item["availability"] = "in_stock"
        item["stock_status"] = "in_stock"
        return item

    # 4) Nessuna informazione certa: UNKNOWN, mai IN STOCK per supposizione.
    item["available"] = None
    item["availability"] = "unknown"
    item["stock_status"] = "unknown"
    return item


def resolve_actual_price(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizza il prezzo mostrato da ScentHunter al prezzo realmente pagabile.

    Problema risolto: alcuni scraper possono intercettare il prezzo unitario
    (es. 26,66 €/100 ml) invece del prezzo della confezione (es. 39,99 €).
    Prima prova la pagina prodotto; solo se non è disponibile usa il calcolo
    da prezzo unitario quando il campo lo dichiara esplicitamente.
    """
    item = dict(product)
    raw_price = str(item.get("price") or "").strip()
    size = _product_size_ml(item)

    # Se lo scraper ha già fornito un prezzo di confezione, lo manteniamo.
    # La pagina viene riaperta solo quando manca il prezzo oppure quando il
    # valore è esplicitamente un prezzo unitario (/100 ml).
    is_unit_price = bool(re.search(r"(?:/|per\s*)100\s*ml", raw_price, re.I))
    if raw_price and not is_unit_price:
        parsed_existing = price_num(raw_price)
        if parsed_existing is not None:
            item["price_value"] = parsed_existing
            return item

    url = str(item.get("url") or "").strip()
    if url:
        try:
            request = Request(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "Mozilla/5.0 (compatible; ScentHunter/1.0)",
                },
            )
            with urlopen(request, timeout=4) as response:
                html = response.read().decode("utf-8", errors="ignore")
            actual = _price_from_structured_html(html, size)
            if actual is not None:
                item["price"] = f"{actual:.2f} €"
                item["price_value"] = actual
                return item
        except Exception:
            pass

    # Fallback sicuro: converti SOLO quando il testo dichiara esplicitamente
    # che il valore è un prezzo unitario per 100 ml.
    unit_match = re.search(r"(?:/|per\s*)100\s*ml", raw_price, re.I)
    if unit_match and size and size > 0:
        unit = price_num(raw_price[:unit_match.start()])
        if unit is not None:
            actual = round(unit * size / 100.0, 2)
            item["price"] = f"{actual:.2f} €"
            item["price_value"] = actual

    return item


def _contains_marker(name: str, markers: set[str]) -> bool:
    name_n = norm(name)
    return any(
        norm(marker) and norm(marker) in name_n
        for marker in markers
    )


def _is_allowed_perfume_name(name: str) -> bool:
    """
    Generic category filter based only on the product identity/name.

    The description, related products and page copy are deliberately ignored:
    they can mention unrelated categories without changing what the product is.

    Known perfume-set names are allowed. Explicitly non-perfume product names
    are rejected before any query matching is applied.
    """
    name_n = norm(name)
    if not name_n:
        return False

    if _contains_marker(name_n, NON_PERFUME_MARKERS):
        return False

    if _contains_marker(name_n, PERFUME_SET_MARKERS):
        return True

    # "kit" is too generic to allow blindly. If it is explicitly a
    # fragrance/perfume kit, it is allowed; otherwise it is rejected.
    if re.search(r"\bkit\b", name_n):
        return _contains_marker(name_n, PERFUME_TYPE_MARKERS)

    # A normal perfume does not need to contain "parfum", "EDP", etc. in
    # its title. The exclusion list above is what defines non-perfume items.
    return True


def _norm(value: Any) -> str:
    value = str(value or "").lower().strip()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


NON_PERFUME = {
    "tester", "testeur", "testing", "sample", "echantillon",
    "mystery box", "mysterybox",
    "shampoo", "shampoing", "shampooing", "conditioner",
    "hair mask", "hair care", "gel douche", "shower gel", "body wash",
    "body lotion", "lotion corps", "body cream", "body creme",
    "body butter", "hand cream", "hand creme", "handcreme",
    "face cream", "face creme", "facial cream", "moisturizer",
    "moisturiser", "creme visage", "serum", "serum visage",
    "deodorant", "deo spray", "deodorant spray",
    "after shave", "aftershave", "baume apres rasage",
    "after shave balm", "lipstick", "rouge a levres",
    "makeup", "maquillage", "foundation", "concealer", "mascara",
    "eyeliner", "liquid blush", "blush liquide", "bronzer",
    "highlighter", "nail polish", "vernis",
    "cosmetic", "cosmetique", "cosmetics", "cosmetiques",
    "skincare", "skin care",
}


def _is_allowed_perfume_name(name: str) -> bool:
    normalized = _norm(name)
    if not normalized:
        return False

    tokens = set(normalized.split())

    for marker in NON_PERFUME:
        marker_tokens = set(_norm(marker).split())
        if marker_tokens and marker_tokens.issubset(tokens):
            return False

    return True


def matches(product: Dict[str, Any], query: str) -> bool:
    name = str(
        product.get("name")
        or product.get("title")
        or product.get("product_name")
        or ""
    ).strip()

    if not name:
        return False

    if not _is_allowed_perfume_name(name):
        return False

    name_normalized = _norm(name)
    name_tokens = set(name_normalized.split())

    if not name_tokens:
        return False

    query_tokens = [
        token
        for token in _norm(query).split()
        if token not in IGNORED_WORDS
    ]

    if not query_tokens:
        query_tokens = _norm(query).split()

    return bool(query_tokens) and all(
        token in name_tokens
        for token in query_tokens
    )


def load_scraper(store: str):
    return importlib.import_module(f"scrapers.{store}.scraper")


def build_search_attempts(store: str, query: str) -> List[str]:
    attempts = [query]
    normalized_query = norm(query)

    if store == "bplatz":
        compact = re.sub(
            r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
            "",
            normalized_query,
        )
        if compact and compact not in attempts:
            attempts.append(compact)

        for token in normalized_query.split():
            if token and token not in attempts:
                attempts.append(token)

    return attempts


def run_store(store: str, query: str) -> List[Dict[str, Any]]:
    module = load_scraper(store)
    search_fn = getattr(module, "search", None)

    if not callable(search_fn):
        raise RuntimeError(f"{store}: scraper senza funzione search()")

    attempts = build_search_attempts(store, query)
    output: List[Dict[str, Any]] = []
    seen = set()
    stock_cache: Dict[str, Optional[bool]] = {}

    for attempt in attempts:
        results = search_fn(attempt) or []

        for item in results:
            if not isinstance(item, dict):
                continue

            product = dict(item)
            product.setdefault("store", store)

            # Regola generale stock: prima normalizziamo la disponibilità.
            # Se è OOS, non sprechiamo una seconda richiesta per il prezzo.
            product = normalize_stock(product, stock_cache)
            if product.get("available") is not False:
                product = resolve_actual_price(product)

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


def unique_results(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
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


def sort_by_price(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def key(product):
        availability = str(product.get("availability") or "").lower()
        is_oos = (product.get("available") is False) or _stock_value_is_oos(availability)
        is_unknown = availability == "unknown" or product.get("available") is None
        value = price_num(product.get("price"))
        # IN STOCK -> UNKNOWN -> OUT OF STOCK. Il prezzo ordina solo dentro lo stesso stato.
        state = 2 if is_oos else (1 if is_unknown else 0)
        return (state, float("inf") if value is None else value)

    return sorted(products, key=key)


def search_perfume(query: str) -> Dict[str, Any]:
    query = str(query or "").strip()
    if not query:
        return {"query": query, "count": 0, "results": [], "comparisons": [], "errors": {}}

    results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    executor = ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="scent-store",
    )
    future_to_store = {
        executor.submit(run_store, store, query): store
        for store in STORES
    }

    done, not_done = wait(future_to_store, timeout=45)

    for future in done:
        store = future_to_store[future]
        try:
            results.extend(future.result() or [])
        except Exception as exc:
            errors[store] = str(exc) or exc.__class__.__name__

    for future in not_done:
        store = future_to_store[future]
        errors[store] = "timeout"
        future.cancel()

    executor.shutdown(wait=False, cancel_futures=True)

    results = sort_by_price(unique_results(results))

    return {
        "query": query,
        "count": len(results),
        "results": results,
        "comparisons": [],
        "errors": errors,
    }


@app.get("/search")
def search(q: str):
    return search_perfume(q)


@app.get("/diagnose")
def diagnose(store: str = "notino", q: str = ""):
    """Diagnostic endpoint for a scraper that exposes diagnose(query)."""
    store = str(store or "").strip().lower()
    query = str(q or "").strip()

    if store not in STORES:
        raise HTTPException(
            status_code=400,
            detail=f"Store non valido. Disponibili: {', '.join(STORES)}",
        )
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    try:
        module = load_scraper(store)
        diagnose_fn = getattr(module, "diagnose", None)

        if not callable(diagnose_fn):
            raise HTTPException(
                status_code=404,
                detail=f"{store}: diagnostico non disponibile",
            )

        return diagnose_fn(query)
    except HTTPException:
        raise
    except Exception as error:
        traceback.print_exc()
        return {
            "status": "error",
            "store": store,
            "query": query,
            "errors": [{
                "stage": "diagnostic_endpoint",
                "type": error.__class__.__name__,
                "message": str(error),
            }],
        }


@app.get("/test-store")
def test_store(store: str, q: str):
    """Endpoint diagnostico per testare un solo scraper."""
    store = str(store or "").strip().lower()
    query = str(q or "").strip()

    if store not in STORES:
        raise HTTPException(
            status_code=400,
            detail=f"Store non valido. Disponibili: {', '.join(STORES)}",
        )
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

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


def load_history() -> Dict[str, Any]:
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as file:
            data = json.load(file)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
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
    return {"status": "healthy", "stores": STORES}


def fragella_search(query: str, limit: int = 10) -> List[Dict[str, Any]]:
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
        payload = json.loads(response.read().decode("utf-8"))

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

        name = str(item.get("Name") or item.get("name") or "").strip()
        brand = str(item.get("Brand") or item.get("brand") or "").strip()
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
    tokens = [token for token in query_n.split() if len(token) >= 2]
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

        if not _is_allowed_perfume_name(name):
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

        ranked.append((priority, position, len(name_n), name_n, item))

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
            print("Catalog suggest error:", repr(error))
        except Exception:
            traceback.print_exc()

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
                    brand = str(product.get("brand") or "").strip()
                    haystack = norm(f"{brand} {name}")
                    words = [word for word in query.split() if word]

                    if not all(word in haystack for word in words):
                        continue

                    if not _is_allowed_perfume_name(name):
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


@app.get("/product")
def product(name: str, brand: str = ""):
    data = search_perfume(name)
    offers: List[Dict[str, Any]] = []

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
        (offer["image"] for offer in offers if offer.get("image")),
        "",
    )

    lowest_price = best_offer.get("price") if best_offer else None

    return {
        "name": name,
        "brand": brand,
        "image": image,
        "lowest_price": lowest_price,
        "best_offer": best_offer,
        "offers": offers,
        "history": history,
        "errors": data["errors"],
        "message": "" if offers else "Nessuna offerta disponibile al momento",
    }
