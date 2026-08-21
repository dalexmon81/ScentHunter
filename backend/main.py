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

try:
    from product_index import ProductIndex
except Exception:
    ProductIndex = None


# ============================================================
# ScentHunter API
# ============================================================

app = FastAPI(
    title="ScentHunter API",
    version="1.0.0",
)

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

NON_PERFUME = {
    # Confezioni / prodotti multipli: non sono una singola referenza profumo.
    "gift set",
    "set regalo",
    "set",
    "discovery set",
    "fragrance set",
    "perfume set",
    "parfum set",
    "coffret",
    "coffret cadeau",
    "cofanetto",
    "bundle",
    "pack",
    "travel set",
    "kit",
    "duo",
    "trio",
    "mystery box",
    "gift box",
    # Prodotti non costituiti dalla singola referenza profumo.
    "tester",
    "testeur",
    "sample",
    "shampoo",
    "shower gel",
    "body wash",
    "body lotion",
    "body cream",
    "body milk",
    "deodorant",
    "deo spray",
    "aftershave",
    "after shave",
    "body spray",
    "hair mist",
    "makeup",
    "cosmetics",
    "cosmetic",
    "skincare",
    "skin care",
    "cosmetici",
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

GLOBAL_SEARCH_TIMEOUT = 120

# Local index is checked first. The live search remains the generic fallback
# while the catalog is being populated.
LOCAL_INDEX_PATH = Path(BASE_DIR) / "scenthunter_index.db"
TEST_INDEX_PATH = Path("/tmp/scenthunter_index_test.db")


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
    value = re.sub(r"[^a-z0-9]+", " ", value)
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
    source = product.get("source")
    source_image = source.get("image") if isinstance(source, dict) else None
    return (
        product.get("image")
        or product.get("image_url")
        or product.get("thumbnail")
        or source_image
        or ""
    )


def nested_value(value: Any) -> Any:
    if isinstance(value, dict):
        return value.get("value")
    return value


def product_field(product: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = product.get(key)
        if value not in (None, ""):
            return str(nested_value(value)).strip()
    return ""


def identity_value(product: Dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = product.get(key)
        if value not in (None, ""):
            value = nested_value(value)
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
    explicit = (
        product.get("size_ml")
        or product.get("volume_ml")
        or product.get("format_ml")
    )
    explicit = nested_value(explicit)

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

    source = product.get("source")
    source_name = source.get("source_name") if isinstance(source, dict) else ""

    text = " ".join(
        str(product.get(key) or "")
        for key in (
            "name",
            "title",
            "product_name",
            "size",
            "format",
            "volume",
        )
    )
    text += " " + str(source_name or "")

    match = re.search(
        r"\b(\d{1,4}(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
        re.I,
    )
    if not match:
        return None

    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None

    if match.group(2).lower() == "cl":
        value *= 10

    return value


def product_concentration(product: Dict[str, Any]) -> str:
    value = product_field(product, "concentration")
    if value:
        return norm(value)

    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        value = nested_value(attributes.get("concentration"))
        if value:
            return norm(value)

    text = " ".join(
        str(product.get(key) or "")
        for key in ("name", "title", "product_name")
    )
    text = norm(text)

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
    if isinstance(offer, dict):
        value = offer.get("availability")
        if value:
            return norm(value)

    value = product.get("availability")
    if value:
        return norm(value)

    if "available" in product:
        available = product.get("available")
        if available is True:
            return "in stock"
        if available is False:
            return "out of stock"

    return "unknown"


def product_search_text(product: Dict[str, Any]) -> str:
    values = [
        product.get("name"),
        product.get("title"),
        product.get("product_name"),
        product.get("brand"),
        product.get("source_brand"),
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
    ]

    attributes = product.get("attributes")
    if isinstance(attributes, dict):
        for value in attributes.values():
            values.append(nested_value(value))

    source = product.get("source")
    if isinstance(source, dict):
        values.extend(
            [
                source.get("source_name"),
                source.get("source_brand"),
                source.get("name"),
                source.get("brand"),
            ]
        )

    return norm(" ".join(str(value or "") for value in values))


def has_small_size(product: Dict[str, Any]) -> bool:
    size = product_size_ml(product)
    if size is not None:
        return size <= 10

    text = product_search_text(product)
    for match in re.finditer(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*ml\b",
        text,
    ):
        try:
            if float(match.group(1).replace(",", ".")) <= 10:
                return True
        except ValueError:
            continue

    return False


# ============================================================
# VALIDAZIONE
# ============================================================

def matches(product: Dict[str, Any], query: str) -> bool:
    query_normalized = norm(query)
    if not query_normalized:
        return False

    search_text = product_search_text(product)
    if not search_text:
        return False

    query_has_size = bool(
        re.search(
            r"(?<!\d)\d+(?:[.,]\d+)?\s*(?:ml|cl)\b",
            query_normalized,
        )
    )

    if has_small_size(product) and not query_has_size:
        return False

    name = norm(
        " ".join(
            str(product.get(key) or "")
            for key in ("name", "title", "product_name")
        )
    )

    for phrase in NON_PERFUME:
        phrase_normalized = norm(phrase)
        if (
            phrase_normalized in name
            and phrase_normalized not in query_normalized
        ):
            return False

    tokens = [
        token
        for token in query_normalized.split()
        if token not in IGNORED_WORDS
    ]

    if not tokens:
        return False

    return all(token in search_text for token in tokens)


# ============================================================
# DISCOVERY GENERICA
# ============================================================

def build_search_attempts(store: str, query: str) -> List[str]:
    """
    Costruisce una sequenza corta e deterministica di query generiche,
    ordinate dalla più precisa alla più permissiva.

    Il parametro store resta nella firma per compatibilità con il codice
    esistente, ma NON modifica le strategie in base al negozio.
    """
    del store

    raw = str(query or "").strip()
    normalized = norm(raw)

    if not raw or not normalized:
        return []

    attempts: List[str] = []
    seen = set()

    def add(value: str) -> None:
        value = str(value or "").strip()
        key = norm(value)
        if value and key and key not in seen:
            seen.add(key)
            attempts.append(value)

    # 1) Query originale: è sempre la discovery più precisa.
    add(raw)

    # 2) Query normalizzata senza parole puramente descrittive.
    tokens = [
        token
        for token in normalized.split()
        if token not in IGNORED_WORDS
    ]

    if tokens:
        add(" ".join(tokens))

    # 3) Forma compatta per siti che indicizzano "100ml" e "100 ml"
    #    come stringhe diverse.
    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )
    add(compact)

    return attempts


# ============================================================
# PREZZO
# ============================================================

def _price_from_structured_html(html: str) -> Optional[float]:
    html = html or ""

    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html,
        re.I | re.S,
    )

    def walk(value):
        if isinstance(value, dict):
            offers = value.get("offers")

            if isinstance(offers, dict):
                for key in ("price", "lowPrice"):
                    value_price = price_num(offers.get(key))
                    if value_price is not None:
                        yield value_price

            elif isinstance(offers, list):
                for offer in offers:
                    if isinstance(offer, dict):
                        for key in ("price", "lowPrice"):
                            value_price = price_num(offer.get(key))
                            if value_price is not None:
                                yield value_price

            for child in value.values():
                yield from walk(child)

        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for raw in scripts:
        try:
            payload = json.loads(raw.strip())
        except Exception:
            continue

        prices = list(walk(payload))
        if prices:
            return prices[0]

    patterns = [
        r'<meta[^>]+(?:property|name)=["\'](?:product:price:amount|og:price:amount)["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+itemprop=["\']price["\'][^>]+content=["\']([^"\']+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, html, re.I)
        if match:
            value_price = price_num(match.group(1))
            if value_price is not None:
                return value_price

    return None


def resolve_actual_price(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Corregge il caso generico in cui il prezzo esposto dal risultato
    sia esplicitamente un prezzo unitario per 100 ml.

    Non apre la pagina prodotto se il prezzo è già un prezzo di vendita
    normale. In questo modo la fase centrale non trasforma una discovery
    con molti risultati in una sequenza di richieste aggiuntive.
    """
    item = dict(product)
    raw_price = str(item.get("price") or "").strip()
    size = product_size_ml(item)

    unit_match = re.search(
        r"(?:/|per\s*)100\s*ml",
        raw_price,
        re.I,
    )

    if unit_match and size and size > 0:
        unit = price_num(raw_price[:unit_match.start()])

        if unit is not None:
            actual = round(unit * size / 100.0, 2)
            item["price"] = f"{actual:.2f} €"
            item["price_value"] = actual

    return item


# ============================================================
# IDENTITA / DEDUPLICAZIONE
# ============================================================

def product_identity_key(product: Dict[str, Any]) -> tuple:
    store = norm(product.get("store", ""))

    variant_id = identity_value(
        product,
        "store_variant_id",
        "variant_id",
    )
    product_id = identity_value(
        product,
        "store_product_id",
        "product_id",
        "catalog_id",
    )
    gtin = identity_value(
        product,
        "gtin",
        "ean",
        "ean13",
        "barcode",
        "upc",
    )
    sku = identity_value(
        product,
        "sku",
    )

    if variant_id:
        return ("variant", store, norm(variant_id))

    if product_id:
        return ("product", store, norm(product_id), norm(product.get("name", "")))

    if gtin:
        return ("gtin", store, norm(gtin))

    if sku:
        return ("sku", store, norm(sku))

    name = norm(
        product_field(
            product,
            "name",
            "title",
            "product_name",
        )
    )

    source = product.get("source")
    if isinstance(source, dict):
        if not name:
            name = norm(source.get("source_name", ""))

    size = product_size_ml(product)
    concentration = product_concentration(product)

    return (
        "fallback",
        store,
        name,
        size,
        concentration,
    )


def unique_results(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique: List[Dict[str, Any]] = []
    seen = set()

    for product in products:
        key = product_identity_key(product)

        if key in seen:
            continue

        seen.add(key)
        unique.append(product)

    return unique


def deterministic_result_key(product: Dict[str, Any]) -> tuple:
    store = norm(product.get("store", ""))
    price = price_num(product.get("price"))

    if price is None:
        price_key = float("inf")
    else:
        price_key = round(price, 4)

    name = norm(
        product_field(
            product,
            "name",
            "title",
            "product_name",
        )
    )

    url = str(product.get("url") or "").strip().lower()

    availability = product_availability(product)

    availability_rank = {
        "in stock": 0,
        "in_stock": 0,
        "available": 0,
        "out of stock": 1,
        "out_of_stock": 1,
        "unknown": 2,
    }.get(availability, 3)

    store_rank = (
        STORES.index(store)
        if store in STORES
        else len(STORES)
    )

    return (
        price_key,
        availability_rank,
        store_rank,
        name,
        url,
    )


def sort_by_price(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        products,
        key=deterministic_result_key,
    )


# ============================================================
# SCRAPER
# ============================================================

def load_scraper(store: str):
    return importlib.import_module(
        f"scrapers.{store}.scraper"
    )


def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    """
    Esegue la discovery generica dello store.

    Le query di fallback vengono usate SOLO se il tentativo precedente
    non ha prodotto alcun risultato valido. Questo evita di ripetere
    inutilmente discovery costose su store che hanno già trovato il prodotto.
    """
    module = load_scraper(store)

    search_fn = getattr(module, "search", None)

    if not callable(search_fn):
        search_fn = getattr(module, "scrape", None)

    if not callable(search_fn):
        raise RuntimeError(
            f"{store}: scraper senza funzione search()/scrape()"
        )

    attempts = build_search_attempts(
        store,
        query,
    )

    output: List[Dict[str, Any]] = []
    seen = set()

    for attempt in attempts:
        try:
            results = search_fn(attempt) or []
        except Exception as exc:
            # Un singolo tentativo fallito non annulla le altre discovery.
            print(
                f"STORE_DISCOVERY_ERROR: store={store} "
                f"attempt={attempt!r} error={type(exc).__name__}: {exc}",
                flush=True,
            )
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

            seen.add(key)

            if matches(product, query):
                output.append(product)
                attempt_added += 1

        # Se una discovery ha già trovato almeno un risultato valido,
        # non eseguiamo fallback ulteriori: il prodotto è stato scoperto.
        # Questo è importante soprattutto per scraper con sitemap o browser.
        if attempt_added > 0:
            break

    return output


# ============================================================
# RICERCA LOCALE
# ============================================================

def _local_index_path() -> Path:
    """
    Resolve the active local index.

    Production uses the persistent backend DB. During the temporary STEP 3
    test, the test DB is also accepted so we can verify the new search path
    without rebuilding the catalog.
    """
    configured = os.getenv("SCENTHUNTER_INDEX_DB", "").strip()
    if configured:
        return Path(configured)

    if LOCAL_INDEX_PATH.exists():
        return LOCAL_INDEX_PATH

    if TEST_INDEX_PATH.exists():
        return TEST_INDEX_PATH

    return LOCAL_INDEX_PATH


def local_search_perfume(query: str) -> Optional[Dict[str, Any]]:
    """
    Search only the local SQLite/FTS5 index.

    Returns None when the local index is unavailable or has no matching
    product. The caller can then use the existing live discovery fallback.
    """
    if ProductIndex is None:
        return None

    db_path = _local_index_path()
    if not db_path.exists():
        return None

    try:
        with ProductIndex(db_path) as index:
            products = index.search_products(query, limit=20)

            if not products:
                return None

            results: List[Dict[str, Any]] = []

            for product in products:
                product_id = str(product.get("product_id") or "").strip()
                if not product_id:
                    continue

                offers = index.get_offers(product_id)

                for offer in offers:
                    item = dict(offer)

                    canonical_brand = str(
                        product.get("brand_name") or ""
                    ).strip()
                    canonical_name = str(
                        product.get("family_name") or ""
                    ).strip()

                    # Keep the existing frontend contract: each offer is
                    # returned as a normal search result.
                    item["brand"] = canonical_brand
                    item["source_brand"] = canonical_brand
                    item["name"] = (
                        str(item.get("name") or "").strip()
                        or canonical_name
                    )
                    item["product_name"] = canonical_name
                    item["canonical_brand"] = canonical_brand
                    item["canonical_name"] = canonical_name
                    item["catalog_id"] = product_id
                    item["product_identity"] = product_id

                    if item.get("size_ml") is not None:
                        item["format_ml"] = item["size_ml"]

                    if item.get("concentration"):
                        item["canonical_concentration"] = item[
                            "concentration"
                        ]

                    if item.get("price") is not None:
                        item["price_value"] = float(item["price"])
                        item["price"] = (
                            f"{float(item['price']):.2f} €"
                        )

                    if item.get("url"):
                        item["source_url"] = item["url"]

                    results.append(item)

            if not results:
                return None

            results = sort_by_price(
                unique_results(results)
            )

            return {
                "query": query,
                "count": len(results),
                "results": results,
                "comparisons": [],
                "errors": {},
                "source": "local_index",
            }

    except Exception as exc:
        print(
            "LOCAL_INDEX_SEARCH_ERROR:",
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return None


def search_with_local_first(query: str) -> Dict[str, Any]:
    """
    Local-first search.

    Indexed products return immediately from SQLite/FTS5. If the local
    catalog does not contain the query yet, the existing live discovery
    remains available as a generic fallback.
    """
    local = local_search_perfume(query)

    if local is not None:
        return local

    live = search_perfume(query)
    live["source"] = "live_fallback"
    return live


def local_autocomplete(
    query: str,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    if ProductIndex is None:
        return []

    db_path = _local_index_path()
    if not db_path.exists():
        return []

    try:
        with ProductIndex(db_path) as index:
            return index.autocomplete(
                query,
                limit=max(1, min(int(limit), 12)),
            )
    except Exception as exc:
        print(
            "LOCAL_AUTOCOMPLETE_ERROR:",
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        return []


# ============================================================
# SEARCH CENTRALE
# ============================================================

def search_perfume(query: str) -> Dict[str, Any]:
    query = str(query or "").strip()

    if not query:
        return {
            "query": "",
            "count": 0,
            "results": [],
            "comparisons": [],
            "errors": {},
        }

    all_results: List[Dict[str, Any]] = []
    errors: Dict[str, str] = {}

    # Tutti gli store partono contemporaneamente.
    # L'ordine dei future NON viene usato per determinare l'ordine finale.
    executor = ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="scent_store",
    )

    futures = {
        executor.submit(run_store, store, query): store
        for store in STORES
    }

    try:
        try:
            completed = as_completed(
                futures,
                timeout=GLOBAL_SEARCH_TIMEOUT,
            )

            for future in completed:
                store = futures[future]

                try:
                    store_results = future.result()
                    if isinstance(store_results, list):
                        all_results.extend(store_results)

                except Exception as exc:
                    errors[store] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    traceback.print_exc()

        except TimeoutError:
            # Alla scadenza globale non perdiamo i future che sono terminati
            # proprio in prossimità del limite. Il vecchio codice controllava
            # solo future.done() e, se un future era già terminato ma non era
            # stato ancora consumato dall'iteratore as_completed(), lo
            # considerava implicitamente riuscito ma ne perdeva il risultato.
            #
            # Ora raccogliamo esplicitamente ogni future già terminato.
            # Solo quelli realmente ancora in esecuzione vengono marcati
            # come timeout.
            for future, store in futures.items():
                if future.done():
                    try:
                        store_results = future.result()
                        if isinstance(store_results, list):
                            all_results.extend(store_results)

                    except Exception as exc:
                        errors[store] = (
                            f"{type(exc).__name__}: {exc}"
                        )
                        traceback.print_exc()
                else:
                    errors[store] = (
                        "Timeout: ricerca del negozio oltre il limite globale"
                    )

    finally:
        # cancel() annulla solamente future non ancora partiti.
        # Non fingiamo di poter interrompere thread già in esecuzione.
        for future, store in futures.items():
            if not future.done():
                future.cancel()

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
        "comparisons": [],
        "errors": errors,
    }


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

    price_value = price_num(
        best_offer.get("price")
    )

    if price_value is None:
        return history

    point = {
        "date": datetime.now(
            timezone.utc
        ).isoformat(),
        "value": price_value,
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
        save_history(history_data)

    return history


# ============================================================
# API
# ============================================================


@app.get(
    "/",
    include_in_schema=False,
)
def root():
    if not FRONTEND_INDEX.exists():
        raise HTTPException(
            status_code=500,
            detail="frontend/index.html non trovato",
        )

    return FileResponse(
        FRONTEND_INDEX
    )


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "stores": STORES,
    }


@app.get("/search")
def search(q: str):
    return search_with_local_first(q)


@app.get("/routing")
def routing(q: str):
    return {
        "query": str(q or "").strip(),
        "stores": list(STORES),
    }


@app.get("/test-indexer")
def test_indexer(
    limit: int = 1,
    offset: int = 0,
    stores: str = "",
    workers: int = 4,
    token: str = "",
):
    """
    TEMPORARY real indexer test endpoint.

    It is intentionally isolated from /search. It runs a small sample of the
    canonical catalog through the existing real scraper pipeline and writes
    to the application local SQLite index so the next local-search test can
    read exactly the same database.

    Remove this endpoint after the STEP 3 real-world test.
    """
    expected_token = os.getenv("SCENTHUNTER_INDEX_TEST_TOKEN", "").strip()
    if expected_token and token != expected_token:
        raise HTTPException(
            status_code=403,
            detail="Token test non valido",
        )

    try:
        sample_limit = max(1, min(int(limit), 3))
        sample_offset = max(0, int(offset))
        worker_count = max(1, min(int(workers), 8))

        selected_stores = [
            value.strip().lower()
            for value in str(stores or "").split(",")
            if value.strip()
        ]

        for store in selected_stores:
            if store not in STORES:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "Store non valido. Disponibili: "
                        + ", ".join(STORES)
                    ),
                )

        from pathlib import Path as _Path
        from indexer import (
            CATALOG_PATH as INDEXER_CATALOG_PATH,
            DEFAULT_STORES as INDEXER_DEFAULT_STORES,
            refresh as refresh_index,
        )

        selected_stores = (
            selected_stores
            if selected_stores
            else list(INDEXER_DEFAULT_STORES)
        )

        test_db = _local_index_path()

        started = datetime.now(timezone.utc)

        stats = refresh_index(
            catalog_path=INDEXER_CATALOG_PATH,
            db_path=test_db,
            stores=selected_stores,
            workers=worker_count,
            offset=sample_offset,
            limit=sample_limit,
        )

        finished = datetime.now(timezone.utc)
        elapsed = (
            finished - started
        ).total_seconds()

        return {
            "ok": True,
            "test": "indexer",
            "temporary": True,
            "sample": {
                "limit": sample_limit,
                "offset": sample_offset,
            },
            "stores": selected_stores,
            "workers": worker_count,
            "elapsed_seconds": round(elapsed, 2),
            "stats": stats,
        }

    except HTTPException:
        raise

    except Exception as error:
        traceback.print_exc()

        return {
            "ok": False,
            "test": "indexer",
            "temporary": True,
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }


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
            "results": sort_by_price(
                unique_results(results)
            ),
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
# SUGGEST
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

    params = urlencode(
        {
            "search": query,
            "limit": max(
                1,
                min(int(limit), 10),
            ),
        }
    )

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
            response.read().decode(
                "utf-8"
            )
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

        output.append(
            {
                "name": name,
                "brand": brand,
                "store": brand or "ScentHunter",
                "image": image,
                "catalog_id": (
                    item.get("_id")
                    or item.get("id")
                ),
            }
        )

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
            item.get("name")
            or ""
        ).strip()

        brand = str(
            item.get("brand")
            or ""
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

        if any(
            norm(phrase) in name_n
            for phrase in NON_PERFUME
        ):
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

        ranked.append(
            (
                priority,
                position,
                len(name_n),
                name_n,
                item,
            )
        )

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

    try:
        catalog_results: List[
            Dict[str, Any]
        ] = []

        catalog_seen = set()

        for item in fragella_search(
            raw_query,
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

        return {
            "query": q,
            "count": len(suggestions),
            "suggestions": suggestions[:8],
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

    return {
        "query": q,
        "count": 0,
        "suggestions": [],
        "source": "catalog",
    }


@app.get("/autocomplete")
def autocomplete(q: str):
    raw_query = str(q or "").strip()
    query = norm(raw_query)

    if len(query) < 2:
        return {
            "query": q,
            "count": 0,
            "suggestions": [],
            "source": "local_index",
        }

    local = local_autocomplete(raw_query, limit=8)

    if local:
        suggestions = []
        for item in local:
            suggestions.append(
                {
                    "catalog_id": item.get("product_id"),
                    "name": item.get("family_name") or "",
                    "brand": item.get("brand_name") or "",
                    "concentration": item.get("concentration") or "",
                }
            )

        return {
            "query": q,
            "count": len(suggestions),
            "suggestions": suggestions,
            "source": "local_index",
        }

    return suggest(q)


# ============================================================
# LOCAL INDEX TEST
# ============================================================
@app.get("/index-stats")
def index_stats():
    if ProductIndex is None:
        return {
            "ok": False,
            "error": "ProductIndex non disponibile",
        }

    db_path = _local_index_path()

    if not db_path.exists():
        return {
            "ok": True,
            "exists": False,
            "path": str(db_path),
            "stats": {
                "products": 0,
                "offers": 0,
                "stores": 0,
            },
        }

    try:
        with ProductIndex(db_path) as index:
            return {
                "ok": True,
                "exists": True,
                "path": str(db_path),
                "stats": index.stats(),
            }
    except Exception as error:
        return {
            "ok": False,
            "path": str(db_path),
            "error": f"{type(error).__name__}: {error}",
        }



@app.get("/index-products")
def index_products(limit: int = 20):
    """
    Diagnostic endpoint for the persistent local index.

    Returns canonical products currently stored in the same SQLite database
    used by the local-first search. No live scraper is called.
    """
    if ProductIndex is None:
        return {
            "ok": False,
            "error": "ProductIndex non disponibile",
        }

    db_path = _local_index_path()

    if not db_path.exists():
        return {
            "ok": True,
            "exists": False,
            "path": str(db_path),
            "products": [],
        }

    try:
        with ProductIndex(db_path) as index:
            rows = index.connection.execute(
                """
                SELECT
                    product_id,
                    brand_name,
                    family_name,
                    concentration,
                    gender,
                    aliases_json,
                    updated_at
                FROM products
                ORDER BY brand_name, family_name
                LIMIT ?
                """,
                (max(1, min(int(limit), 100)),),
            ).fetchall()

            products = []
            for row in rows:
                item = dict(row)
                item["aliases"] = json.loads(
                    item.pop("aliases_json") or "[]"
                )
                products.append(item)

            return {
                "ok": True,
                "exists": True,
                "path": str(db_path),
                "stats": index.stats(),
                "products": products,
            }

    except Exception as error:
        traceback.print_exc()
        return {
            "ok": False,
            "path": str(db_path),
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }


@app.get("/test-local-search")
def test_local_search(q: str):
    query = str(q or "").strip()

    if not query:
        raise HTTPException(
            status_code=400,
            detail="Parametro q mancante",
        )

    started = datetime.now(timezone.utc)

    try:
        result = local_search_perfume(query)
        finished = datetime.now(timezone.utc)

        return {
            "ok": result is not None,
            "query": query,
            "source": (
                "local_index"
                if result is not None
                else "empty_or_unavailable"
            ),
            "elapsed_seconds": round(
                (finished - started).total_seconds(),
                4,
            ),
            "result": result,
            "index_path": str(_local_index_path()),
        }

    except Exception as error:
        traceback.print_exc()
        return {
            "ok": False,
            "query": query,
            "source": "local_index",
            "error": f"{type(error).__name__}: {error}",
            "traceback": traceback.format_exc(),
        }


# ============================================================
# PRODUCT
# ============================================================

@app.get("/product")
def product(
    name: str,
    brand: str = "",
):
    data = search_perfume(name)

    offers: List[
        Dict[str, Any]
    ] = []

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
        key=lambda offer: (
            offer["price_value"],
            norm(offer.get("store", "")),
            norm(offer.get("name", "")),
            str(offer.get("url", "")).lower(),
        )
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
# TEMPORARY NOTINO DIAGNOSTIC
# Remove this entire section after testing.
# ============================================================

@app.get("/diagnose-notino-module")
def diagnose_notino_module():
    try:
        module = importlib.import_module("scrapers.notino.scraper")

        return {
            "ok": True,
            "store": "notino",
            "module": module.__name__,
            "file": getattr(module, "__file__", None),
            "has_search": callable(getattr(module, "search", None)),
            "has_scrape": callable(getattr(module, "scrape", None)),
            "has_diagnose": callable(getattr(module, "diagnose", None)),
            "has_internal_search": callable(
                getattr(module, "_search_internal", None)
            ),
            "has_browser_discover": callable(
                getattr(module, "browser_discover", None)
            ),
            "has_http_discovery": callable(
                getattr(module, "_search_http_candidates", None)
            ),
            "has_candidate_extractor": callable(
                getattr(module, "extract_candidates_from_html", None)
            ),
        }

    except Exception as exc:
        return {
            "ok": False,
            "store": "notino",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


@app.get("/diagnose-notino")
def diagnose_notino(q: str):
    query = str(q or "").strip()

    if not query:
        return {
            "ok": False,
            "store": "notino",
            "error": "empty_query",
        }

    try:
        module = importlib.import_module("scrapers.notino.scraper")
        diagnose_fn = getattr(module, "diagnose", None)

        if not callable(diagnose_fn):
            return {
                "ok": False,
                "store": "notino",
                "query": query,
                "error": "Notino scraper has no diagnose() function",
            }

        return {
            "ok": True,
            "store": "notino",
            "query": query,
            "diagnostic": diagnose_fn(query),
        }

    except Exception as exc:
        return {
            "ok": False,
            "store": "notino",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }


@app.get("/diagnose-notino-search")
def diagnose_notino_search(q: str):
    query = str(q or "").strip()

    if not query:
        return {
            "ok": False,
            "store": "notino",
            "error": "empty_query",
        }

    try:
        module = importlib.import_module("scrapers.notino.scraper")
        debug_fn = getattr(module, "debug_search", None)

        if not callable(debug_fn):
            return {
                "ok": False,
                "store": "notino",
                "query": query,
                "error": "Notino scraper has no debug_search() function",
            }

        return {
            "ok": True,
            "store": "notino",
            **debug_fn(query),
        }

    except Exception as exc:
        return {
            "ok": False,
            "store": "notino",
            "query": query,
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }
