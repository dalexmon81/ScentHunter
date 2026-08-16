from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

import importlib
import json
import os
import re
import traceback
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin
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
    # Queste non sono varianti da scartare globalmente:
    # - Liquid Brun Limited Edition deve comparire nella ricerca "Liquid Brun".
    # - Hawas Kobra e' una linea distinta e viene gestita con la regola
    #   contestuale piu' sotto.
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
    Evita risultati palesemente diversi dalla ricerca.

    Esempio:
    se si cerca "9 PM", non devono entrare automaticamente
    "9 PM Rebel", "9 PM Elixir", ecc.
    """
    name = norm(product.get("name", ""))
    query_normalized = norm(query)
    search_text = product_search_text(product)

    if not name:
        return False

    # Mini-taglie/campioni (es. 2 ml) non devono entrare nelle offerte
    # normali. Se un giorno l'utente cercherà esplicitamente "2 ml",
    # la regola verrà resa permissiva in base alla query.
    query_has_size = bool(
        re.search(r"(?<!\d)\d+(?:[.,]\d+)?\s*ml\b", query_normalized)
    )
    if has_small_size(product) and not query_has_size:
        return False

    # Le varianti realmente generiche restano escluse quando non sono
    # richieste esplicitamente. Non inseriamo qui "limited edition" o
    # "kobra": entrambe possono essere prodotti che l'utente vuole
    # trovare come risultato della linea cercata.
    for phrase in VARIANTS:
        normalized_phrase = norm(phrase)

        if (
            normalized_phrase in search_text
            and normalized_phrase not in query_normalized
        ):
            return False

    # Hawas for Him e Hawas Kobra sono due linee diverse. Deloox e alcuni
    # scraper possono descrivere Kobra come "Hawas Kobra for Him"; in quel
    # caso il semplice controllo dei token farebbe passare il prodotto.
    # Rendiamo quindi esplicita questa distinzione, senza toccare le altre
    # ricerche Hawas.
    if query_normalized == "hawas for him" and "kobra" in name:
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
    """Poche query mirate: precisa prima, poi più corta."""
    raw = str(query or "").strip()
    normalized = norm(raw)
    attempts: List[str] = []

    def add(value: str) -> None:
        value = str(value or "").strip()
        if value and norm(value) not in [norm(x) for x in attempts]:
            attempts.append(value)

    add(raw)

    tokens = [t for t in normalized.split() if t not in IGNORED_WORDS]

    # Spesso la prima parola è il marchio:
    # Rasasi Hawas for Him -> Hawas Him
    # Lattafa Asad Bourbon -> Asad Bourbon
    if len(tokens) >= 2:
        add(" ".join(tokens[1:]))

    # Query ancora più semplice per motori che lavorano male con nomi lunghi.
    if len(tokens) >= 3:
        add(" ".join(tokens[-2:]))
    elif tokens:
        add(" ".join(tokens))

    compact = re.sub(
        r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
        "",
        normalized,
    )
    if compact != normalized:
        add(compact)

    return attempts[:3]

def run_store(
    store: str,
    query: str,
) -> List[Dict[str, Any]]:
    """
    Esegue la ricerca su un singolo negozio.
    """
    module = load_scraper(store)

    attempts = build_search_attempts(
        store,
        query,
    )

    output: List[Dict[str, Any]] = []
    seen = set()

    for attempt in attempts:

        results = module.search(attempt) or []

        for item in results:

            if not isinstance(item, dict):
                continue

            product = dict(item)

            product.setdefault(
                "store",
                store,
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

        if output:
            break

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

    # NON 8 insieme: su Render Free abbiamo osservato exit 137.
    # Due worker riducono nettamente RAM e connessioni simultanee.
    executor = ThreadPoolExecutor(max_workers=2)
    futures = {
        executor.submit(run_store, store, query): store
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

    results = sort_by_price(unique_results(all_results))

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
# API - DIAGNOSTICA HTTP DELOOX (UNA SOLA RICHIESTA)
# ============================================================

@app.get("/diagnose-deloox-category")
def diagnose_deloox_category(q: str):
    """
    Diagnostica esclusivamente una singola richiesta HTTP alla categoria Liquid Brun di Deloox.
    NON chiama lo scraper, ricerca interna, sitemap o pagine prodotto.
    """
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    url = "https://www.deloox.com/en/category/1132834/liquid-brun.html"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    started = time.monotonic()

    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=8) as response:
            body = response.read()
            elapsed_ms = round((time.monotonic() - started) * 1000)

            return {
                "query": query,
                "url": url,
                "status": response.status,
                "elapsed_ms": elapsed_ms,
                "response_bytes": len(body),
                "content_type": response.headers.get("Content-Type"),
                "error": None,
            }

    except HTTPError as error:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "query": query,
            "url": url,
            "status": error.code,
            "elapsed_ms": elapsed_ms,
            "response_bytes": 0,
            "content_type": error.headers.get("Content-Type") if error.headers else None,
            "error": f"HTTPError: {error}",
        }

    except URLError as error:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "query": query,
            "url": url,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "response_bytes": 0,
            "content_type": None,
            "error": f"URLError: {error.reason}",
        }

    except Exception as error:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "query": query,
            "url": url,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "response_bytes": 0,
            "content_type": None,
            "error": f"{type(error).__name__}: {error}",
        }


# ============================================================
# API - DIAGNOSTICA ESTRAZIONE URL PRODOTTO DELOOX
# ============================================================

@app.get("/diagnose-deloox-products")
def diagnose_deloox_products(q: str):
    """
    Secondo step diagnostico: una sola richiesta alla categoria Deloox,
    poi esegue esclusivamente il parser degli URL prodotto del vero scraper.
    NON apre nessuna pagina prodotto e NON esegue discover/search.
    """
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    url = "https://www.deloox.com/en/category/1132834/liquid-brun.html"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    started = time.monotonic()

    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=8) as response:
            body = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type")

        # Usa ESATTAMENTE il parser del vero scraper Deloox.
        module = load_scraper("deloox")
        extractor = getattr(module, "_candidate_product_urls")
        product_urls = extractor(body.decode("utf-8", errors="ignore"), query)

        elapsed_ms = round((time.monotonic() - started) * 1000)

        return {
            "query": query,
            "url": url,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "response_bytes": len(body),
            "content_type": content_type,
            "product_url_count": len(product_urls),
            "product_urls": product_urls[:20],
            "parser": "scrapers.deloox.scraper._candidate_product_urls",
            "error": None,
        }

    except HTTPError as error:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "query": query,
            "url": url,
            "status": error.code,
            "elapsed_ms": elapsed_ms,
            "response_bytes": 0,
            "product_url_count": 0,
            "product_urls": [],
            "parser": "not_run",
            "error": f"HTTPError: {error}",
        }

    except URLError as error:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "query": query,
            "url": url,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "response_bytes": 0,
            "product_url_count": 0,
            "product_urls": [],
            "parser": "not_run",
            "error": f"URLError: {error.reason}",
        }

    except Exception as error:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        traceback.print_exc()
        return {
            "query": query,
            "url": url,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "response_bytes": 0,
            "product_url_count": 0,
            "product_urls": [],
            "parser": "error",
            "error": f"{type(error).__name__}: {error}",
        }


# ============================================================
# API - DIAGNOSTICA RAW VS PARSER DELOOX
# ============================================================

@app.get("/diagnose-deloox-products-raw")
def diagnose_deloox_products_raw(q: str):
    """
    Terzo step diagnostico: separa il contenuto realmente ricevuto da Deloox
    dal filtro del parser.

    Fa UNA sola richiesta HTTP alla categoria Liquid Brun.
    NON apre pagine prodotto e NON esegue discover/search.

    Serve a distinguere questi casi:
      A) Deloox invia davvero un solo URL prodotto;
      B) Deloox invia molti URL ma il parser non li riconosce;
      C) gli URL sono presenti nel JavaScript/JSON ma non come normali <a>.
    """
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    url = "https://www.deloox.com/en/category/1132834/liquid-brun.html"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    started = time.monotonic()

    try:
        request = Request(url, headers=headers, method="GET")
        with urlopen(request, timeout=8) as response:
            body = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type")

        html = body.decode("utf-8", errors="ignore")
        module = load_scraper("deloox")
        soup = module.BeautifulSoup(html, "html.parser")

        # 1) Tutte le occorrenze testuali di /product/ nel documento.
        all_product_paths = re.findall(
            r"(?:https?:)?//(?:www\\.)?deloox\\.com[^\"'<>\\s]*?/product/[^\"'<>\\s]+|(?:/)(?:en/|it/|nl/)?product/[^\"'<>\\s]+",
            html,
            re.I,
        )

        # 2) URL prodotto esposti da normali tag <a>.
        anchor_product_urls = []
        for a in soup.find_all("a", href=True):
            href = str(a.get("href") or "")
            if "/product/" in href.lower():
                absolute = urljoin("https://www.deloox.com", href).split("#")[0].split("?")[0]
                if absolute not in anchor_product_urls:
                    anchor_product_urls.append(absolute)

        # 3) URL prodotto presenti nei blocchi serializzati/script.
        serialized_product_urls = []
        for tag in soup.find_all(["script", "div", "article", "li"]):
            blob = str(tag)
            if "/product/" not in blob.lower():
                continue
            found = re.findall(
                r"(?:(?:https?:)?//(?:www\\.)?deloox\\.com)?[^\"'<>\\s]*?/product/[^\"'<>\\s]+",
                blob,
                re.I,
            )
            for raw in found:
                absolute = urljoin("https://www.deloox.com", raw).split("#")[0].split("?")[0]
                if "/product/" in absolute.lower() and absolute not in serialized_product_urls:
                    serialized_product_urls.append(absolute)

        # 4) Il risultato del vero parser, per confronto diretto.
        parser_urls = module._candidate_product_urls(html, query)

        elapsed_ms = round((time.monotonic() - started) * 1000)

        return {
            "query": query,
            "url": url,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "response_bytes": len(body),
            "content_type": content_type,
            "raw_product_path_occurrences": len(all_product_paths),
            "anchor_product_url_count": len(anchor_product_urls),
            "anchor_product_urls": anchor_product_urls[:30],
            "serialized_product_url_count": len(serialized_product_urls),
            "serialized_product_urls": serialized_product_urls[:30],
            "parser_product_url_count": len(parser_urls),
            "parser_product_urls": parser_urls[:30],
            "parser": "scrapers.deloox.scraper._candidate_product_urls",
            "error": None,
        }

    except HTTPError as error:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "query": query,
            "url": url,
            "status": error.code,
            "elapsed_ms": elapsed_ms,
            "response_bytes": 0,
            "error": f"HTTPError: {error}",
        }
    except URLError as error:
        elapsed_ms = round((time.monotonic() - started) * 1000)
        return {
            "query": query,
            "url": url,
            "status": None,
            "elapsed_ms": elapsed_ms,
            "response_bytes": 0,
            "error": f"URLError: {error.reason}",
        }
    except Exception as error:
        traceback.print_exc()
        return {
            "query": query,
            "url": url,
            "status": None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "response_bytes": 0,
            "error": f"{type(error).__name__}: {error}",
        }


# ============================================================
# API - DIAGNOSTICA PRODOTTO DELOOX STEP 4
# ============================================================

@app.get("/diagnose-deloox-product")
def diagnose_deloox_product(q: str = "Liquid Brun"):
    """
    Quarto step diagnostico.

    Parte dall'URL prodotto gia' trovato nello STEP 3 e fa UNA sola richiesta
    HTTP alla pagina prodotto. Poi esegue ESATTAMENTE _product() del vero
    scraper Deloox e restituisce i dati necessari per capire se e dove viene
    scartato il prodotto.

    NON esegue search(), discover(), categorie o sitemap.
    """
    query = str(q or "").strip() or "Liquid Brun"
    product_url = (
        "https://www.deloox.com/en/product/1385920/"
        "french-avenue-liquid-brun-extrait-de-parfum-limited-edition-150-ml.html"
    )
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    started = time.monotonic()

    try:
        request = Request(product_url, headers=headers, method="GET")
        with urlopen(request, timeout=8) as response:
            body = response.read()
            status = response.status
            content_type = response.headers.get("Content-Type")

        html = body.decode("utf-8", errors="ignore")
        module = load_scraper("deloox")
        soup = module.BeautifulSoup(html, "html.parser")

        h1 = soup.find("h1")
        h1_name = module.clean(h1.get_text(" ", strip=True)) if h1 else ""
        data = module._jsonld(soup)
        structured_name = module.clean(data.get("name")) if isinstance(data, dict) else ""
        name = h1_name or structured_name
        matches_result = bool(name and module.matches(name, query))

        offers = data.get("offers") if isinstance(data, dict) else None
        offers = offers if isinstance(offers, list) else [offers]
        offer = next((x for x in offers if isinstance(x, dict)), {})
        jsonld_price = module.parse_price(offer.get("price"))
        page_text = soup.get_text(" ", strip=True)
        fallback_price = module.parse_price(page_text)
        selected_size = module._selected_size(soup, data, h1_name)

        # Esecuzione del vero punto di uscita del parser.
        result = module._product(product_url, html, query)

        elapsed_ms = round((time.monotonic() - started) * 1000)

        return {
            "query": query,
            "url": product_url,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "response_bytes": len(body),
            "content_type": content_type,
            "h1_name": h1_name,
            "structured_name": structured_name,
            "name_used_by_product": name,
            "matches_query": matches_result,
            "jsonld_price": jsonld_price,
            "fallback_page_price": fallback_price,
            "selected_size_ml": selected_size,
            "product_result_is_none": result is None,
            "product_result": result,
            "parser": "scrapers.deloox.scraper._product",
            "error": None,
        }

    except HTTPError as error:
        return {
            "query": query,
            "url": product_url,
            "status": error.code,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "response_bytes": 0,
            "error": f"HTTPError: {error}",
        }
    except URLError as error:
        return {
            "query": query,
            "url": product_url,
            "status": None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "response_bytes": 0,
            "error": f"URLError: {error.reason}",
        }
    except Exception as error:
        traceback.print_exc()
        return {
            "query": query,
            "url": product_url,
            "status": None,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "response_bytes": 0,
            "error": f"{type(error).__name__}: {error}",
        }


# ============================================================
# API - DIAGNOSTICA DELOOX DISCOVERY STEP 5
# ============================================================

@app.get("/diagnose-deloox-discovery")
def diagnose_deloox_discovery(q: str):
    """
    Diagnostica il percorso DISCOVERY di Deloox senza chiamare search()/_discover().

    Esegue separatamente:
      1. categorie root -> HTTP
      2. root HTML -> Product Line/category links
      3. Product Line/category -> HTTP
      4. Product Line/category -> URL prodotto

    Ogni richiesta HTTP ha timeout rigido di 4 secondi.
    Nessuna sitemap, nessun endpoint /search, nessuna pagina prodotto.
    """
    query = str(q or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Parametro q mancante")

    started_total = time.monotonic()

    try:
        module = load_scraper("deloox")
        session = module.requests.Session()
        headers = getattr(module, "HEADERS", {})
        timeout = 4

        roots = list(module._category_pages(session))
        seed_urls = list(module._targeted_category_seed_urls(query))

        root_results = []
        all_matching_lines = []

        try:
            for root in roots:
                step_started = time.monotonic()
                row = {
                    "root": root,
                    "http_status": None,
                    "elapsed_ms": None,
                    "bytes": 0,
                    "matching_category_links": [],
                    "direct_product_urls": [],
                    "error": None,
                }

                try:
                    response = session.get(
                        root,
                        headers=headers,
                        timeout=timeout,
                    )
                    row["http_status"] = response.status_code
                    row["elapsed_ms"] = round(
                        (time.monotonic() - step_started) * 1000
                    )
                    row["bytes"] = len(response.content or b"")

                    if response.status_code < 400:
                        try:
                            matching = module._category_product_line_links(
                                response.text,
                                query,
                            )
                        except Exception as exc:
                            matching = []
                            row["error"] = (
                                f"category_parser: {type(exc).__name__}: {exc}"
                            )

                        row["matching_category_links"] = matching[:20]

                        try:
                            direct = module._candidate_product_urls(
                                response.text,
                                query,
                            )
                        except Exception as exc:
                            direct = []
                            row["error"] = (
                                f"product_parser: {type(exc).__name__}: {exc}"
                            )

                        row["direct_product_urls"] = direct[:20]

                        for link in matching:
                            if link not in all_matching_lines:
                                all_matching_lines.append(link)

                except Exception as exc:
                    row["elapsed_ms"] = round(
                        (time.monotonic() - step_started) * 1000
                    )
                    row["error"] = f"{type(exc).__name__}: {exc}"

                root_results.append(row)

            # Step 3: visit ONLY the category/Product Line links that
            # actually matched the query. No blind pagination.
            line_results = []

            for line_url in all_matching_lines[:20]:
                step_started = time.monotonic()
                row = {
                    "category_url": line_url,
                    "http_status": None,
                    "elapsed_ms": None,
                    "bytes": 0,
                    "product_urls": [],
                    "error": None,
                }

                try:
                    response = session.get(
                        line_url,
                        headers=headers,
                        timeout=timeout,
                    )
                    row["http_status"] = response.status_code
                    row["elapsed_ms"] = round(
                        (time.monotonic() - step_started) * 1000
                    )
                    row["bytes"] = len(response.content or b"")

                    if response.status_code < 400:
                        try:
                            products = module._candidate_product_urls(
                                response.text,
                                query,
                            )
                            row["product_urls"] = products[:20]
                        except Exception as exc:
                            row["error"] = (
                                f"product_parser: {type(exc).__name__}: {exc}"
                            )

                except Exception as exc:
                    row["elapsed_ms"] = round(
                        (time.monotonic() - step_started) * 1000
                    )
                    row["error"] = f"{type(exc).__name__}: {exc}"

                line_results.append(row)

            elapsed_total = round(
                (time.monotonic() - started_total) * 1000
            )

            return {
                "query": query,
                "elapsed_total_ms": elapsed_total,
                "strategy": {
                    "discover_called": False,
                    "search_called": False,
                    "sitemap_called": False,
                    "product_pages_called": False,
                    "http_timeout_seconds": timeout,
                },
                "targeted_seed_urls": seed_urls,
                "root_count": len(roots),
                "roots": root_results,
                "matching_category_link_count": len(all_matching_lines),
                "matching_category_links": all_matching_lines[:20],
                "category_pages": line_results,
                "error": None,
            }

        finally:
            session.close()

    except Exception as exc:
        return {
            "query": query,
            "elapsed_total_ms": round(
                (time.monotonic() - started_total) * 1000
            ),
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(limit=3),
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
