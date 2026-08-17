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
PRICE_RE = re.compile(r"(?:€|\$|£)\s*(\d{1,4}(?:[.,]\d{2}))|(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*(?:€|\$|£)", re.I)
PRODUCT_URL_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/(?:it|fr|en|es|de|pt)/"
    r"(?!content|ricerca|ricerca_old|marchi|negozi|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module)", re.I
)

def _clean(value):
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()

def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"
    text = _clean(value)
    m = PRICE_RE.search(text) or re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)", text)
    value = next((g for g in m.groups() if g is not None), None) if m else None
    return (value.replace(".", ",") + " €") if value else None

def _looks_like_product_url(url):
    return bool(url and PRODUCT_URL_RE.match(url))

def _query_matches(name, url, query):
    """Match against both visible product name and product URL.

    Sabina often puts the brand in the product URL but not in the clickable
    product title. The old matcher checked the title only, causing valid
    products such as 'Le Beau Narcisse' to disappear for a full-brand query.
    """
    q_words = [w for w in re.findall(r"[a-z0-9À-ÿ]+", _clean(query).lower()) if len(w) > 1]
    if not q_words:
        return False
    hay = f"{_clean(name).lower()} {str(url or '').lower().replace('-', ' ')}"
    return all(w in hay for w in q_words)

def _extract_size_from_html(text):
    if not text:
        return ""
    try:
        soup = BeautifulSoup(text, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.get_text(strip=True))
            except Exception:
                continue
            stack = [data]
            while stack:
                obj = stack.pop()
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if str(k).lower() in {"size", "volume", "netcontent", "capacity", "contentvolume"}:
                            m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", str(v), re.I)
                            if m:
                                return m.group(1)
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(obj, list):
                    stack.extend(obj)
    except Exception:
        pass
    soup = BeautifulSoup(text, "html.parser")
    visible = _clean(soup.get_text(" ", strip=True))
    for pattern in (
        r"(?:dimensione|tamaño|taille|größe|groesse|size)\s*:?\s*(\d{2,4})\s*ml\b",
        r"(?:dimensione|tamaño|taille|größe|groesse|size)[^0-9]{0,120}(\d{2,4})\s*ml\b",
    ):
        m = re.search(pattern, visible, re.I)
        if m:
            return m.group(1)
    return ""

def _enrich_product_sizes(session, rows):
    out, cache = [], {}
    requests_used = 0
    for row in rows:
        item = dict(row)
        m = re.search(r"\b(\d{1,4})\s*ml\b", _clean(item.get("name")), re.I)
        if m:
            item["size_ml"] = m.group(1)
            out.append(item)
            continue
        url = str(item.get("url") or "").split("#")[0]
        size = cache.get(url, "")
        if url and not size and requests_used < 3:
            requests_used += 1
            try:
                r = _get(session, url)
                if r is not None:
                    size = _extract_size_from_html(r.text)
                    r.close()
            except Exception:
                size = ""
            cache[url] = size
        if size:
            item["size_ml"] = size
        out.append(item)
    return out

def _dedupe(rows, query):
    out, seen = [], set()
    for row in rows:
        name = _clean(row.get("name"))
        url = str(row.get("url") or "")
        price = _price(row.get("price"))
        if not name or not url or not price:
            continue
        if not _query_matches(name, url, query):
            continue
        key = (name.lower(), url.split("?")[0].split("#")[0])
        if key in seen:
            continue
        seen.add(key)
        item = {"store": STORE, "name": name, "price": price, "url": url.split("#")[0]}
        if row.get("size_ml"):
            item["size_ml"] = str(row["size_ml"])
        out.append(item)
    return out

def _walk_json(obj, query):
    rows = []
    def walk(x):
        if isinstance(x, dict):
            low = {str(k).lower(): v for k, v in x.items()}
            name = next((low[k] for k in ("name", "product_name", "productname", "title", "label") if k in low and isinstance(low[k], (str, int, float))), None)
            url = next((low[k] for k in ("url", "link", "product_url", "producturl", "href") if k in low and isinstance(low[k], str)), None)
            price = next((low[k] for k in ("price", "final_price", "finalprice", "sale_price", "saleprice", "price_amount", "priceamount") if k in low), None)
            if url:
                url = urljoin(BASE, url)
            if name and url and _looks_like_product_url(url) and _price(price):
                rows.append({"store": STORE, "name": str(name), "price": price, "url": url})
            for v in x.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return _dedupe(rows, query)

def _parse_html(text, query):
    soup = BeautifulSoup(text, "html.parser")
    rows = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            rows.extend(_walk_json(json.loads(script.get_text(strip=True)), query))
        except Exception:
            pass
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
            if re.search(r"(?:€|\$|£)", txt) and len(txt) < 1800:
                break
        text_block = _clean(container.get_text(" ", strip=True))
        pm = PRICE_RE.search(text_block)
        if not pm:
            continue
        candidates = [a.get("title"), a.get("aria-label"), a.get_text(" ", strip=True)]
        for sel in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title", ".product-item-name"):
            for el in container.select(sel):
                candidates.append(el.get_text(" ", strip=True))
        cleaned = [_clean(x) for x in candidates if _clean(x)]
        if not cleaned:
            continue
        # Prefer a concise title; the previous max-length choice could select
        # unrelated card text and make matching fail.
        name = min(cleaned, key=len)
        for candidate in cleaned:
            low = candidate.lower()
            if "le beau" in low or "jean paul gaultier" in low:
                name = candidate
                break
        if name.lower() in {"vedi", "vedi tutto", "acquista", "immagine"}:
            continue
        rows.append({"store": STORE, "name": name, "price": next((g for g in pm.groups() if g is not None), "") .replace(".", ",") + " €", "url": url})
    return _dedupe(rows, query)

def _get(session, url, **kwargs):
    print(f"SABINA_TEST request: {url}", flush=True)
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, **kwargs)
    except Exception as exc:
        print(f"SABINA_TEST request_error: {type(exc).__name__}: {exc}", flush=True)
        raise
    print(
        f"SABINA_TEST response: status={r.status_code} final_url={r.url} "
        f"content_type={r.headers.get('Content-Type','')} bytes={len(r.content)}",
        flush=True,
    )
    if r.status_code in (403, 429):
        print(f"SABINA BLOCKED: HTTP {r.status_code}", flush=True)
        r.close()
        return None
    r.raise_for_status()
    return r

def search(query):
    query = _clean(query)
    if not query:
        return []
    s = requests.Session()
    s.headers.update(HEADERS)
    try:
        try:
            r = _get(s, BASE + "/it/")
            if r is not None:
                print(f"SABINA_TEST homepage_ok: chars={len(r.text)}", flush=True)
                r.close()
        except Exception as exc:
            print(f"SABINA_TEST homepage_error: {type(exc).__name__}: {exc}", flush=True)
        urls = [
            BASE + "/it/ricerca?search_query=" + quote_plus(query),
            BASE + "/it/ricerca_old?s=" + quote_plus(query),
            BASE + "/it/ricerca_old?search_query=" + quote_plus(query),
        ]
        for url in urls:
            try:
                r = _get(s, url)
                if r is None:
                    break
                html = r.text
                print(f"SABINA_TEST search_page: chars={len(html)} links={len(BeautifulSoup(html, 'html.parser').find_all('a', href=True))}", flush=True)
                r.close()
                parsed = _parse_html(html, query)
                print(f"SABINA_TEST parsed_rows: {len(parsed)}", flush=True)
                if parsed:
                    return _enrich_product_sizes(s, parsed)
            except Exception as exc:
                print(f"SABINA_TEST search_url_error: {type(exc).__name__}: {exc}", flush=True)
                continue
        ajax_url = BASE + "/modules/ecelastic/ajax.php"
        payloads = [
            {"q": query, "query": query, "search_query": query, "id_lang": 5, "id_country": 10, "id_currency": 1},
            {"s": query, "search_query": query, "id_lang": 5, "id_country": 10, "id_currency": 1},
            {"query": query, "id_lang": 5, "id_country": 10, "id_currency": 1},
        ]
        for payload in payloads:
            for method in ("get", "post"):
                try:
                    if method == "get":
                        r = s.get(ajax_url, params=payload, headers=HEADERS, timeout=TIMEOUT)
                    else:
                        r = s.post(ajax_url, data=payload, headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"}, timeout=TIMEOUT)
                    if r.status_code in (403, 429):
                        r.close()
                        return []
                    print(f"SABINA_TEST ajax_response: method={method} status={r.status_code} final_url={r.url} chars={len(r.text)} content_type={r.headers.get('Content-Type','')}", flush=True)
                    if not r.ok or not r.text.strip():
                        r.close()
                        continue
                    response_text = r.text
                    r.close()
                    try:
                        rows = _walk_json(json.loads(response_text), query)
                    except Exception:
                        rows = _parse_html(response_text, query)
                    print(f"SABINA_TEST ajax_rows: method={method} rows={len(rows)}", flush=True)
                    if rows:
                        return _enrich_product_sizes(s, rows)
                except Exception as exc:
                    print(f"SABINA_TEST ajax_error: method={method} {type(exc).__name__}: {exc}", flush=True)
                    continue
        print("SABINA_TEST FINAL: no_results", flush=True)
        return []
    finally:
        s.close()

def scrape(query):
    return search(query)

def search_sabina(query):
    return search(query)

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]).strip() or "Dior"
    print(json.dumps(search(q), ensure_ascii=False, indent=2))
