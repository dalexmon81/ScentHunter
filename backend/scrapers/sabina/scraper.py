import re
import json
import html as html_lib
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 4

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/it/",
}

PRICE_RE = re.compile(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*€")
PRODUCT_URL_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/it/(?!"
    r"(?:content|ricerca|ricerca_old|marchi|negozi|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module)/)"
)


def _clean(value):
    return re.sub(r"\s+", " ", html_lib.unescape(value or "")).strip()


def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"
    text = _clean(str(value))
    m = PRICE_RE.search(text)
    if not m:
        # JSON/API spesso restituisce il numero senza simbolo €
        m = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)", text)
    if not m:
        return None
    return m.group(1).replace(".", ",") + " €"


def _looks_like_product_url(url):
    return bool(url and PRODUCT_URL_RE.match(url))


def _extract_variants_from_html(text):
    """Estrae tutte le varianti formato/prezzo dalla pagina prodotto Sabina.

    Sabina può mostrare più formati nella stessa scheda (es. 75 ML e
    125 ML). La ricerca può invece restituire una sola card senza il formato.
    Per questo leggiamo le varianti direttamente dalla pagina prodotto.
    """
    if not text:
        return []

    soup = BeautifulSoup(text, "html.parser")
    variants = []
    seen = set()

    def add_variant(size, price):
        if not size or not price:
            return
        size = str(size).strip()
        price = _price(price)
        if not price:
            return
        key = (size, price)
        if key not in seen:
            seen.add(key)
            variants.append({"size_ml": size, "price": price})

    def walk(obj):
        if isinstance(obj, dict):
            low = {str(k).lower(): v for k, v in obj.items()}

            size = None
            for key in (
                "size", "volume", "netcontent", "capacity", "contentvolume",
                "description",
            ):
                if key in low:
                    m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", str(low[key]), re.I)
                    if m:
                        size = m.group(1)
                        break

            price = None
            for key in (
                "price", "final_price", "finalprice", "sale_price",
                "saleprice", "price_amount", "priceamount",
            ):
                if key in low:
                    price = low[key]
                    break

            if size and price:
                add_variant(size, price)

            for value in obj.values():
                walk(value)

        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    # 1) JSON-LD / dati strutturati.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
            walk(data)
        except Exception:
            continue

    # 2) Elementi che rappresentano direttamente le opzioni di formato.
    for el in soup.find_all(["option", "label", "li", "button", "span", "div"]):
        txt = _clean(el.get_text(" ", strip=True))
        if not txt or len(txt) > 500:
            continue

        sizes = re.findall(r"(?<!\d)(\d{2,4})\s*ml\b", txt, re.I)
        if not sizes:
            continue

        prices = re.findall(
            r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*[€$£]",
            txt,
        )
        if not prices:
            continue

        if len(sizes) == 1:
            add_variant(sizes[0], prices[0])
        elif len(sizes) == len(prices):
            for size, price in zip(sizes, prices):
                add_variant(size, price)
        else:
            for size in sizes:
                pos = txt.lower().find(size.lower())
                before = txt[max(0, pos - 80):pos]
                after = txt[pos:pos + 160]
                nearby = re.findall(
                    r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*[€$£]",
                    before + " " + after,
                )
                if nearby:
                    add_variant(size, nearby[0])

    # 3) Fallback sul testo visibile.
    visible = _clean(soup.get_text(" ", strip=True))
    for m in re.finditer(r"(?<!\d)(\d{2,4})\s*ml\b", visible, re.I):
        size = m.group(1)
        window = visible[m.start():m.start() + 180]
        pm = re.search(
            r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*[€$£]",
            window,
        )
        if pm:
            add_variant(size, pm.group(1))

    return variants


def _extract_size_from_html(text, preferred_size=""):
    """Compatibilità: restituisce una misura dalla pagina prodotto."""
    variants = _extract_variants_from_html(text)

    preferred = re.search(
        r"(?<!\d)(\d{2,4})\s*ml\b",
        str(preferred_size or ""),
        re.I,
    )
    if preferred:
        wanted = preferred.group(1)
        for variant in variants:
            if variant["size_ml"] == wanted:
                return wanted

    return variants[0]["size_ml"] if variants else ""


MAX_SIZE_ENRICH_REQUESTS = 3


def _enrich_product_sizes(session, rows, query=""):
    """Espande una scheda Sabina nelle sue varianti reali di formato/prezzo.

    Una ricerca senza formato deve restituire TUTTE le varianti presenti nella
    pagina prodotto (es. 30/50/100 ml), non soltanto la prima variante.
    Una ricerca con formato, invece, restituisce esclusivamente quel formato.
    """
    enriched = []
    cache = {}
    enrichment_requests = 0

    requested_size = ""
    m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", _clean(query), re.I)
    if m:
        requested_size = m.group(1)

    for row in rows:
        base_item = dict(row)
        name = _clean(base_item.get("name"))
        existing = re.search(r"\b(\d{1,4})\s*ml\b", name, re.I)

        url = str(base_item.get("url") or "").split("#")[0]
        if not url:
            if existing:
                base_item["size_ml"] = existing.group(1)
            enriched.append(base_item)
            continue

        if existing and not requested_size:
            base_item["size_ml"] = existing.group(1)
            enriched.append(base_item)
            continue

        if url in cache:
            variants = cache[url]
        elif enrichment_requests >= MAX_SIZE_ENRICH_REQUESTS:
            variants = []
        else:
            variants = []
            enrichment_requests += 1
            try:
                r = _get(session, url)
                if r is not None:
                    page = r.text
                    r.close()
                    variants = _extract_variants_from_html(page)
            except Exception:
                variants = []
            cache[url] = variants

        if requested_size:
            selected = next(
                (v for v in variants if v["size_ml"] == requested_size),
                None,
            )
            if selected:
                item = dict(base_item)
                item["size_ml"] = selected["size_ml"]
                item["price"] = selected["price"]
                enriched.append(item)
            else:
                # Non fingiamo che una variante diversa sia quella richiesta.
                continue
        elif variants:
            # IMPORTANTISSIMO: una pagina prodotto può contenere più formati.
            # Creiamo un'offerta per ogni variante reale, mantenendo la stessa
            # URL/nome prodotto; sarà poi il grouping centrale a riunirle nella
            # stessa scheda e a mostrare i formati disponibili.
            for variant in variants:
                item = dict(base_item)
                item["size_ml"] = variant["size_ml"]
                item["price"] = variant["price"]
                enriched.append(item)
        else:
            # Se non riusciamo a leggere le varianti, manteniamo il risultato
            # della ricerca senza inventare un formato.
            enriched.append(base_item)

    return enriched


def _clean_product_name(value):
    """Rimuove dal titolo solo testo commerciale/prezzo evidentemente estraneo."""
    name = _clean(value)
    if not name:
        return ""

    # Alcune risposte/card possono restituire titoli del tipo:
    # "Fleur De Lait Pour Femme De 63,50€". Il prezzo non fa parte
    # dell'identità del prodotto e non deve creare una seconda scheda.
    name = re.sub(
        r"\s+(?:de\s+)?\d{1,4}(?:[.,]\d{2})\s*[€$£]\s*$",
        "",
        name,
        flags=re.I,
    )
    name = re.sub(r"\s+", " ", name).strip(" -–—|:")
    return name


def _dedupe(rows, query):
    q = _clean(query).lower()

    # Il formato è un filtro sulla variante, non una parola che deve essere
    # necessariamente presente nel nome della card di ricerca.
    words = [
        w for w in re.findall(r"[a-z0-9À-ÿ]+", q)
        if len(w) > 1 and w != "ml" and not w.isdigit()
    ]

    out, seen = [], set()

    for row in rows:
        name = _clean_product_name(row.get("name"))
        url = row.get("url")
        price = _price(row.get("price"))

        if not name or not url or not price:
            continue

        hay = name.lower()
        if words and not all(w in hay for w in words):
            continue

        size = str(row.get("size_ml") or "").strip()
        key = (url.split("?")[0].lower(), size)
        if key in seen:
            continue
        seen.add(key)

        item = {
            "store": STORE,
            "name": name,
            "price": price,
            "url": url.split("#")[0],
        }
        if size:
            item["size_ml"] = size
        out.append(item)

    return out


def _walk_json(obj, query):
    """Estrae prodotti da JSON anche se SellBoost cambia leggermente i nomi dei campi."""
    rows = []

    def walk(x):
        if isinstance(x, dict):
            low = {str(k).lower(): v for k, v in x.items()}

            name = next(
                (low[k] for k in (
                    "name", "product_name", "productname", "title", "label"
                ) if k in low and isinstance(low[k], (str, int, float))),
                None,
            )
            url = next(
                (low[k] for k in (
                    "url", "link", "product_url", "producturl", "href"
                ) if k in low and isinstance(low[k], str)),
                None,
            )
            price = next(
                (low[k] for k in (
                    "price", "final_price", "finalprice", "sale_price",
                    "saleprice", "price_amount", "priceamount"
                ) if k in low),
                None,
            )

            if url:
                url = urljoin(BASE, url)
            if name and url and _looks_like_product_url(url) and _price(price):
                rows.append({
                    "store": STORE,
                    "name": str(name),
                    "price": price,
                    "url": url,
                })

            for v in x.values():
                walk(v)

        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(obj)
    return _dedupe(rows, query)


def _parse_html(text, query):
    soup = BeautifulSoup(text, "html.parser")
    rows = []

    # 1) JSON-LD: è il dato più pulito quando presente.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
            rows.extend(_walk_json(data, query))
        except Exception:
            pass

    # 2) Card / link prodotto. Non dipende da UNA singola classe CSS.
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a["href"])
        if not _looks_like_product_url(url):
            continue

        container = a
        for _ in range(7):
            parent = getattr(container, "parent", None)
            if not parent:
                break
            container = parent
            txt = _clean(container.get_text(" ", strip=True))
            if "€" in txt and len(txt) < 1800:
                break

        text_block = _clean(container.get_text(" ", strip=True))
        pm = PRICE_RE.search(text_block)
        if not pm:
            continue

        # Preferenza: titolo strutturato della card; poi title/aria-label;
        # solo alla fine il testo grezzo del link. In questo modo non
        # incorporiamo prezzo, sconto o altre informazioni nel nome prodotto.
        candidates = []

        for sel in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title"):
            el = container.select_one(sel)
            if el:
                candidates.append(el.get_text(" ", strip=True))

        candidates.extend([
            a.get("title"),
            a.get("aria-label"),
            a.get_text(" ", strip=True),
        ])

        name = next(
            (
                _clean(x)
                for x in candidates
                if _clean(x)
                and _clean(x).lower() not in {"vedi", "vedi tutto", "acquista", "immagine"}
            ),
            "",
        )
        if not name or name.lower() in {"vedi", "vedi tutto", "acquista", "immagine"}:
            continue

        rows.append({
            "store": STORE,
            "name": name,
            "price": pm.group(1) + " €",
            "url": url,
        })

    return _dedupe(rows, query)


class StoreRequestError(RuntimeError):
    def __init__(self, status, message, *, http_status=None):
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def _get(session, url, **kwargs):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT,
                        allow_redirects=True, **kwargs)
    except requests.Timeout as exc:
        raise StoreRequestError("timeout", str(exc)) from exc
    except requests.ConnectionError as exc:
        raise StoreRequestError("unavailable", str(exc)) from exc
    except requests.RequestException as exc:
        raise StoreRequestError("error", str(exc)) from exc

    if r.status_code in (403, 429):
        status = "blocked"
    elif 500 <= r.status_code <= 599:
        status = "unavailable"
    elif 400 <= r.status_code <= 499:
        status = "error"
    else:
        status = None

    if status:
        code = r.status_code
        r.close()
        raise StoreRequestError(status, f"HTTP {code}", http_status=code)
    return r

def search(query):
    """Generic Sabina discovery with bounded parallel first-party probes.

    Sabina exposes several search mechanisms. Running them sequentially made
    the scraper spend most of its store timeout budget on mechanisms that had
    already failed before reaching the useful one. Each mechanism is now
    isolated and probed in parallel; the first verified product rows win.
    Transport failures remain technical failures and can never become
    NOT_FOUND.
    """
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)
    transport_errors = []
    successful_http = False

    try:
        queries = [query]
        query_without_size = _clean(
            re.sub(r"(?<!\d)\d{2,4}\s*ml\b", " ", query, flags=re.I)
        )
        if query_without_size and query_without_size.casefold() != query.casefold():
            queries.append(query_without_size)

        search_urls = []
        for search_query in queries:
            encoded = quote_plus(search_query)
            search_urls.extend([
                BASE + "/it/ricerca?search_query=" + encoded,
                BASE + "/it/ricerca_old?s=" + encoded,
                BASE + "/it/ricerca_old?search_query=" + encoded,
            ])

        def fetch_search(url):
            try:
                r = _get(session, url)
                text = r.text
                r.close()
                return ("ok", url, text, None)
            except StoreRequestError as exc:
                return ("error", url, None, exc)

        # One bounded round instead of six sequential 4-second requests.
        with ThreadPoolExecutor(max_workers=min(6, len(search_urls))) as pool:
            futures = [pool.submit(fetch_search, url) for url in search_urls]
            for future in as_completed(futures):
                kind, url, text, error = future.result()
                if kind == "error":
                    transport_errors.append(error)
                    continue

                successful_http = True
                rows = _parse_html(text, query)
                if rows:
                    return _enrich_product_sizes(
                        session,
                        rows,
                        query,
                    )

        # First-party AJAX fallback. Keep this bounded too. It is only reached
        # when the normal search pages answered successfully but produced no
        # product rows, or when they all failed technically.
        ajax_url = BASE + "/modules/ecelastic/ajax.php"
        payloads = []
        for search_query in queries:
            payloads.extend([
                {"q": search_query, "query": search_query,
                 "search_query": search_query, "id_lang": 5,
                 "id_country": 10, "id_currency": 1},
                {"s": search_query, "search_query": search_query,
                 "id_lang": 5, "id_country": 10, "id_currency": 1},
            ])

        def fetch_ajax(payload):
            local = []
            for method in ("get", "post"):
                try:
                    if method == "get":
                        r = session.get(
                            ajax_url,
                            params=payload,
                            headers=HEADERS,
                            timeout=TIMEOUT,
                        )
                    else:
                        r = session.post(
                            ajax_url,
                            data=payload,
                            headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                            timeout=TIMEOUT,
                        )

                    if r.status_code in (403, 429):
                        local.append(StoreRequestError("blocked", f"HTTP {r.status_code}", http_status=r.status_code))
                        r.close()
                        continue
                    if 500 <= r.status_code <= 599:
                        local.append(StoreRequestError("unavailable", f"HTTP {r.status_code}", http_status=r.status_code))
                        r.close()
                        continue
                    if 400 <= r.status_code <= 499:
                        local.append(StoreRequestError("error", f"HTTP {r.status_code}", http_status=r.status_code))
                        r.close()
                        continue

                    text = r.text
                    r.close()
                    if not text.strip():
                        continue

                    try:
                        rows = _walk_json(json.loads(text), query)
                    except Exception:
                        rows = _parse_html(text, query)
                    if rows:
                        return ("rows", rows, local)
                    successful = True
                    return ("empty", [], local)
                except requests.Timeout as exc:
                    local.append(StoreRequestError("timeout", str(exc)))
                except requests.ConnectionError as exc:
                    local.append(StoreRequestError("unavailable", str(exc)))
                except requests.RequestException as exc:
                    local.append(StoreRequestError("error", str(exc)))
            return ("error", [], local)

        with ThreadPoolExecutor(max_workers=min(4, len(payloads))) as pool:
            futures = [pool.submit(fetch_ajax, payload) for payload in payloads]
            for future in as_completed(futures):
                kind, rows, local_errors = future.result()
                transport_errors.extend(local_errors)
                if kind == "rows" and rows:
                    return _enrich_product_sizes(session, rows, query)
                if kind == "empty":
                    successful_http = True

        if not successful_http and transport_errors:
            priority = {"blocked": 0, "timeout": 1, "unavailable": 2, "error": 3}
            raise sorted(
                transport_errors,
                key=lambda exc: priority.get(exc.status, 99),
            )[0]

        return []
    finally:
        session.close()

def search_stream(query, emit=None):
    """Return the common ScentHunter scraper report."""
    query = _clean(query)
    if not query:
        return {
            "status": "success", "verified": True, "results": [],
            "error": None, "details": {"reason": "empty_query"},
        }

    try:
        rows = search(query)
    except StoreRequestError as exc:
        return {
            "status": exc.status, "verified": False, "results": [],
            "error": str(exc), "details": {"http_status": exc.http_status},
        }
    except requests.Timeout as exc:
        return {
            "status": "timeout", "verified": False, "results": [],
            "error": str(exc), "details": {},
        }
    except requests.ConnectionError as exc:
        return {
            "status": "unavailable", "verified": False, "results": [],
            "error": str(exc), "details": {},
        }
    except requests.RequestException as exc:
        return {
            "status": "error", "verified": False, "results": [],
            "error": str(exc), "details": {},
        }
    except Exception as exc:
        return {
            "status": "error", "verified": False, "results": [],
            "error": str(exc),
            "details": {"exception": type(exc).__name__},
        }

    rows = rows if isinstance(rows, list) else []
    if emit is not None:
        for row in rows:
            emit(row)

    if rows:
        return {
            "status": "success", "verified": True, "results": rows,
            "error": None, "details": {"count": len(rows)},
        }

    return {
        "status": "partial", "verified": False, "results": [],
        "error": None,
        "details": {
            "count": 0,
            "reason": "no_results_without_authoritative_empty_verification",
        },
    }


# Alias compatibili con gli altri scraper del progetto.
def scrape(query):
    return search_stream(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]).strip() or "Dior"
    data = search(q)
    print(json.dumps(data, ensure_ascii=False, indent=2))
