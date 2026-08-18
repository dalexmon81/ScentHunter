import re
import json
import html as html_lib
from urllib.parse import quote_plus, urljoin, urlparse, parse_qs, unquote

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 8
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/es/",
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
    """Extract product records from arbitrary nested JSON-LD structures.

    Sabina's Product JSON-LD keeps the product identity at the Product level
    while the price normally lives one level deeper inside offers. The old
    walker only accepted a price on the same object as name/url, so valid
    product pages could be discovered but then rejected during validation.
    """
    rows = []

    def json_price(value):
        if isinstance(value, dict):
            low = {str(k).lower(): v for k, v in value.items()}
            for key in (
                "price",
                "final_price",
                "finalprice",
                "sale_price",
                "saleprice",
                "price_amount",
                "priceamount",
            ):
                if key in low and _price(low[key]):
                    return low[key]
            for key in ("offers", "offer", "pricespecification", "price_specification"):
                if key in low:
                    found = json_price(low[key])
                    if found is not None:
                        return found
        elif isinstance(value, list):
            for item in value:
                found = json_price(item)
                if found is not None:
                    return found
        return None

    def walk(x):
        if isinstance(x, dict):
            low = {str(k).lower(): v for k, v in x.items()}
            name = next(
                (
                    low[k]
                    for k in ("name", "product_name", "productname", "title", "label")
                    if k in low and isinstance(low[k], (str, int, float))
                ),
                None,
            )
            url = next(
                (
                    low[k]
                    for k in ("url", "link", "product_url", "producturl", "href")
                    if k in low and isinstance(low[k], str)
                ),
                None,
            )
            if url:
                url = urljoin(BASE, url)

            price = json_price(x)
            if (
                name
                and url
                and _looks_like_product_url(url)
                and price is not None
            ):
                rows.append(
                    {
                        "store": STORE,
                        "name": str(name),
                        "price": price,
                        "url": url,
                    }
                )

            for value in x.values():
                if isinstance(value, (dict, list)):
                    walk(value)

        elif isinstance(x, list):
            for value in x:
                walk(value)

    walk(obj)
    return _dedupe(rows, query)

def _parse_html(text, query):
    soup = BeautifulSoup(text or "", "html.parser")
    rows = []

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            rows.extend(_walk_json(json.loads(script.get_text(strip=True)), query))
        except Exception:
            pass

    tokens = [t for t in re.findall(r"[a-z0-9à-ÿ]+", _clean(query).lower()) if len(t) > 1]

    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a["href"])
        if not _looks_like_product_url(url):
            continue

        clean_url = url.split("#", 1)[0].split("?", 1)[0]
        url_hay = clean_url.lower().replace("-", " ")

        # The URL itself is the strongest generic identity signal available
        # on Sabina product cards. If it contains every query token, discovery
        # is allowed even when the visible card title is incomplete.
        url_match = tokens and all(token in url_hay for token in tokens)

        container = a
        best_container = a
        for _ in range(6):
            parent = getattr(container, "parent", None)
            if not parent:
                break
            container = parent
            classes = " ".join(container.get("class", [])) if hasattr(container, "get") else ""
            marker = (classes + " " + str(container.get("id", ""))).lower() if hasattr(container, "get") else ""
            txt = _clean(container.get_text(" ", strip=True))
            if len(txt) <= 2200:
                best_container = container
            if any(term in marker for term in ("product", "item", "card", "ajax_block")):
                break

        text_block = _clean(best_container.get_text(" ", strip=True))
        if not re.search(r"(?:€|\$|£)", text_block):
            continue

        candidates = [a.get("title"), a.get("aria-label"), a.get_text(" ", strip=True)]
        for sel in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title", ".product-item-name"):
            for el in best_container.select(sel):
                candidates.append(el.get_text(" ", strip=True))

        cleaned = [_clean(x) for x in candidates if _clean(x)]
        if not cleaned:
            continue

        token_candidates = [
            c for c in cleaned
            if len(c) <= 500 and all(token in c.lower().replace("-", " ") for token in tokens)
        ]

        if token_candidates:
            name = min(token_candidates, key=len)
        elif url_match:
            # When the slug is the only complete identity signal, choose the
            # most product-like concise heading rather than arbitrary page text.
            name = min(cleaned, key=len)
        else:
            continue

        if name.lower() in {"vedi", "vedi tutto", "acquista", "immagine"}:
            continue

        pm = PRICE_RE.search(text_block)
        if not pm:
            continue

        price_value = next((g for g in pm.groups() if g is not None), "")
        rows.append({
            "store": STORE,
            "name": name,
            "price": price_value.replace(".", ",") + " €",
            "url": clean_url,
        })

    return _dedupe(rows, query)

def _get(session, url, **kwargs):
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, **kwargs)
    if r.status_code in (403, 429):
        print(f"SABINA BLOCKED: HTTP {r.status_code}")
        r.close()
        return None
    r.raise_for_status()
    return r

def _extract_search_engine_urls(text, query):
    """Generic external discovery fallback.

    Used only when Sabina's own search endpoints do not expose product links.
    The query is supplied at runtime; no product, brand or URL is hard-coded.
    """
    soup = BeautifulSoup(text, "html.parser")
    found = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = html_lib.unescape(str(a.get("href") or ""))
        candidate = href

        # Google/Bing/DDG may wrap the real URL in a redirect parameter.
        parsed = urlparse(href)
        params = parse_qs(parsed.query)
        for key in ("url", "q", "uddg"):
            if params.get(key):
                candidate = unquote(params[key][0])
                break

        if candidate.startswith("/"):
            candidate = urljoin("https://www.google.com", candidate)

        candidate = candidate.replace("&amp;", "&")
        if not _looks_like_product_url(candidate):
            continue

        clean_url = candidate.split("#", 1)[0].split("?", 1)[0]
        if clean_url in seen:
            continue

        anchor_text = _clean(a.get_text(" ", strip=True))
        tokens = [t for t in re.findall(r"[a-z0-9à-ÿ]+", _clean(query).lower()) if len(t) > 1]
        url_hay = clean_url.lower().replace("-", " ")
        text_hay = anchor_text.lower().replace("-", " ")
        if tokens and (all(t in url_hay for t in tokens) or (len(text_hay) <= 500 and all(t in text_hay for t in tokens))):
            seen.add(clean_url)
            found.append(clean_url)

    return found


def _discover_from_external_search(session, query):
    """Generic last-resort discovery through public search indexes."""
    q = quote_plus(f"site:sabina.com {query}")
    endpoints = [
        f"https://www.google.com/search?q={q}&num=20",
        f"https://www.bing.com/search?q={q}&count=20",
        f"https://html.duckduckgo.com/html/?q={q}",
    ]
    output = []
    seen = set()

    for endpoint in endpoints:
        try:
            response = session.get(
                endpoint,
                headers={**HEADERS, "Referer": "https://www.google.com/"},
                timeout=TIMEOUT,
            )
            if not response.ok:
                continue
            for url in _extract_search_engine_urls(response.text, query):
                if url not in seen:
                    seen.add(url)
                    output.append(url)
            response.close()
            if output:
                break
        except requests.RequestException:
            continue

    return output


def _discover_from_first_party(session, query):
    urls = []
    seen = set()
    q = quote_plus(query)

    # Sabina/PrestaShop installations have used several search routes over
    # time. Try the generic forms rather than depending on one historical URL.
    # Sabina currently serves its working search under the Spanish storefront.
    # Keep the discovery query-driven and generic: no product URL or product name
    # is embedded here. Multiple route variants are retained for resilience.
    search_urls = [
        BASE + "/es/buscar_old?search_query=" + q,
        BASE + "/es/buscar_old?s=" + q,
        BASE + "/es/buscar?search_query=" + q,
        BASE + "/es/buscar?s=" + q,
        BASE + "/es/buscar?controller=search&s=" + q,
        BASE + "/es/search?s=" + q,
    ]

    for url in search_urls:
        try:
            response = _get(session, url)
            if response is None:
                continue
            links = _extract_product_links_from_html(response.text, query)
            response.close()
            for link in links:
                if link not in seen:
                    seen.add(link)
                    urls.append(link)
        except requests.RequestException:
            continue

    # Generic AJAX variants used by search modules.
    ajax_endpoints = [
        BASE + "/es/module/ec_customization/ajax",
        BASE + "/es/modules/ec_customization/ajax",
        BASE + "/modules/ecelastic/ajax.php",
    ]
    payloads = [
        {"s": query, "query": query, "search_query": query},
        {"q": query, "query": query, "search_query": query},
    ]

    for endpoint in ajax_endpoints:
        for payload in payloads:
            for method in ("get", "post"):
                try:
                    if method == "get":
                        response = session.get(endpoint, params=payload, headers=HEADERS, timeout=TIMEOUT)
                    else:
                        response = session.post(
                            endpoint,
                            data=payload,
                            headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                            timeout=TIMEOUT,
                        )
                    if not response.ok:
                        response.close()
                        continue
                    text = response.text
                    response.close()
                    links = _extract_product_links_from_html(text, query)
                    for link in links:
                        if link not in seen:
                            seen.add(link)
                            urls.append(link)
                except requests.RequestException:
                    continue

    return urls


def _extract_product_links_from_html(text, query):
    """Discover candidate product URLs from a Sabina search response.

    Discovery is query-driven. URL tokens are the strongest signal; when a
    product slug does not contain every query token, only the anchor itself or
    a nearby product/card container may supply the textual match. Large parent
    containers are deliberately ignored so one matching result cannot make
    unrelated links look like candidates.
    """
    soup = BeautifulSoup(text or "", "html.parser")
    found = []
    seen = set()
    tokens = [
        t
        for t in re.findall(r"[a-z0-9à-ÿ]+", _clean(query).lower())
        if len(t) > 1
    ]

    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a.get("href") or "").split("#", 1)[0].split("?", 1)[0]
        if not _looks_like_product_url(url):
            continue

        url_hay = url.lower().replace("-", " ")
        url_match = bool(tokens) and all(token in url_hay for token in tokens)

        text_candidates = [
            _clean(a.get("title")),
            _clean(a.get("aria-label")),
            _clean(a.get_text(" ", strip=True)),
        ]

        container = a
        for _ in range(4):
            container = getattr(container, "parent", None)
            if not container:
                break
            classes = " ".join(container.get("class", [])) if hasattr(container, "get") else ""
            marker = (classes + " " + str(container.get("id", ""))).lower() if hasattr(container, "get") else ""
            container_text = _clean(container.get_text(" ", strip=True))
            if len(container_text) <= 700 and any(
                term in marker for term in ("product", "item", "card", "result", "ajax_block")
            ):
                text_candidates.append(container_text)
                break

        text_match = any(
            candidate
            and len(candidate) <= 700
            and all(token in candidate.lower().replace("-", " ") for token in tokens)
            for candidate in text_candidates
        )

        if not tokens or not (url_match or text_match):
            continue

        if url not in seen:
            seen.add(url)
            found.append(url)

    return found

def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Warm-up establishes the same session/cookies used for the search.
        try:
            response = _get(session, BASE + "/es/")
            if response is not None:
                response.close()
        except requests.RequestException:
            pass

        candidate_urls = []
        seen = set()

        # 1. Sabina's own search/AJAX discovery.
        for url in _discover_from_first_party(session, query):
            if url not in seen:
                seen.add(url)
                candidate_urls.append(url)

        # 2. Generic public-index fallback. This is still query-driven and
        # contains no product-specific seed or exception.
        if not candidate_urls:
            for url in _discover_from_external_search(session, query):
                if url not in seen:
                    seen.add(url)
                    candidate_urls.append(url)

        # 3. Fetch the actual product pages and extract product-level data.
        results = []
        seen_results = set()
        for url in candidate_urls[:30]:
            try:
                response = _get(session, url)
                if response is None:
                    continue
                html = response.text
                response.close()
            except requests.RequestException:
                continue

            parsed = _parse_html(html, query)
            for item in parsed:
                key = (
                    item.get("name", "").lower(),
                    item.get("url", "").split("?", 1)[0].split("#", 1)[0],
                    item.get("price", ""),
                )
                if key in seen_results:
                    continue
                seen_results.add(key)
                results.append(item)

        if results:
            return _enrich_product_sizes(session, results)

        return []
    finally:
        session.close()

def scrape(query):
    return search(query)

def search_sabina(query):
    return search(query)

if __name__ == "__main__":
    import sys
    q = " ".join(sys.argv[1:]).strip() or "Dior"
    print(json.dumps(search(q), ensure_ascii=False, indent=2))
