import re
import json
import html as html_lib
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

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
    """Espande una scheda Sabina in tutte le varianti formato/prezzo provate."""
    enriched = []
    cache = {}
    requested_size = ""
    m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", _clean(query), re.I)
    if m:
        requested_size = m.group(1)

    for row in rows:
        item = dict(row)
        url = str(item.get("url") or "").split("#")[0]
        name = _clean(item.get("name"))
        existing = re.search(r"\b(\d{1,4})\s*ml\b", name, re.I)
        variants = []
        if url:
            if url in cache:
                variants = cache[url]
            else:
                try:
                    r = _get(session, url)
                    page = r.text if r is not None else ""
                    if r is not None:
                        r.close()
                    variants = _extract_variants_from_html(page)
                except Exception:
                    variants = []
                cache[url] = variants

        if requested_size:
            selected = next((v for v in variants if str(v.get("size_ml")) == requested_size), None)
            if selected:
                out = dict(item)
                out["size_ml"] = selected["size_ml"]
                out["price"] = selected["price"]
                enriched.append(out)
            elif existing and existing.group(1) == requested_size:
                item["size_ml"] = requested_size
                enriched.append(item)
            continue

        if variants:
            # IMPORTANT: return every real variant, not only variants[0].
            for variant in variants:
                out = dict(item)
                out["size_ml"] = str(variant["size_ml"])
                out["price"] = variant["price"]
                enriched.append(out)
        elif existing:
            item["size_ml"] = existing.group(1)
            enriched.append(item)
        else:
            enriched.append(item)

    return enriched

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
        name = _clean(row.get("name"))
        url = row.get("url")
        price = _price(row.get("price"))

        if not name or not url or not price:
            continue

        hay = name.lower()
        if words and not all(w in hay for w in words):
            continue

        size = str(row.get("size_ml") or "").strip()
        key = (name.lower(), url.split("?")[0], size)
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


def _get(session, url, **kwargs):
    r = session.get(
        url,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
        **kwargs,
    )

    if r.status_code in (403, 429):
        print(f"SABINA BLOCKED: HTTP {r.status_code}")
        r.close()
        return None

    r.raise_for_status()
    return r

def search(query):
    """
    Ricerca Sabina.
    Strategia:
      A) ricerca attuale
      B) ricerca legacy reale di Sabina
      C) endpoint ecelastic del sito
      D) pagina HTML ottenuta dopo inizializzazione sessione

    Ritorna sempre:
      [{"store":"Sabina","name":"...","price":"00,00 €","url":"..."}]
    """
    query = _clean(query)
    if not query:
        return []

    s = requests.Session()
    s.headers.update(HEADERS)
    results = []

    # Crea cookie/sessione come un browser normale.
    try:
        _get(s, BASE + "/it/")
    except Exception:
        pass

    # Sabina può non restituire nulla quando il formato (es. 125 ml)
    # è incluso nella query, anche se il prodotto esiste e la scheda contiene
    # quella variante. Prima proviamo la query completa, poi la stessa query
    # senza il formato; il formato verrà selezionato dalla pagina prodotto.
    queries = [query]
    query_without_size = _clean(
        re.sub(r"(?<!\d)\d{2,4}\s*ml\b", " ", query, flags=re.I)
    )
    if query_without_size and query_without_size.casefold() != query.casefold():
        queries.append(query_without_size)

    urls = []
    for search_query in queries:
        urls.extend([
            BASE + "/it/ricerca?search_query=" + quote_plus(search_query),
            BASE + "/it/ricerca_old?s=" + quote_plus(search_query),
            BASE + "/it/ricerca_old?search_query=" + quote_plus(search_query),
        ])

    try:
        for url in urls:
            try:
                r = _get(s, url)

                # 403/429 significa che Sabina ci sta bloccando:
                # non passiamo subito a un'altra ricerca equivalente.
                if r is None:
                    break

                html = r.text
                r.close()

                parsed = _parse_html(html, query)
                results.extend(parsed)

                if results:
                    return _enrich_product_sizes(s, _dedupe(results, query), query)
            except Exception:
                continue

        # Endpoint ecelastic: manteniamo i payload/metodi originali,
        # ma interrompiamo subito in caso di 403/429.
        ajax_url = BASE + "/modules/ecelastic/ajax.php"
        payloads = [
            {
                "q": query,
                "query": query,
                "search_query": query,
                "id_lang": 5,
                "id_country": 10,
                "id_currency": 1,
            },
            {
                "s": query,
                "search_query": query,
                "id_lang": 5,
                "id_country": 10,
                "id_currency": 1,
            },
            {
                "query": query,
                "id_lang": 5,
                "id_country": 10,
                "id_currency": 1,
            },
        ]

        for payload in payloads:
            for method in ("get", "post"):
                try:
                    fn = getattr(s, method)

                    if method == "get":
                        r = fn(
                            ajax_url,
                            params=payload,
                            headers=HEADERS,
                            timeout=TIMEOUT,
                        )
                    else:
                        r = fn(
                            ajax_url,
                            data=payload,
                            headers={
                                **HEADERS,
                                "X-Requested-With": "XMLHttpRequest",
                            },
                            timeout=TIMEOUT,
                        )

                    if r.status_code in (403, 429):
                        print(f"SABINA AJAX BLOCKED: HTTP {r.status_code}")
                        r.close()
                        return []

                    if not r.ok or not r.text.strip():
                        r.close()
                        continue

                    response_text = r.text
                    r.close()

                    try:
                        data = json.loads(response_text)
                        rows = _walk_json(data, query)
                    except Exception:
                        rows = _parse_html(response_text, query)

                    if rows:
                        return _enrich_product_sizes(s, _dedupe(rows, query), query)

                except Exception:
                    continue

        return []

    finally:
        s.close()


# Alias compatibili con gli altri scraper del progetto.
def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]).strip() or "Dior"
    data = search(q)
    print(json.dumps(data, ensure_ascii=False, indent=2))
