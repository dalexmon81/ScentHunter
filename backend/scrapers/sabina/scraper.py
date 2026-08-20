import json
import html as html_lib
import re
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 8
MAX_SIZE_ENRICH_REQUESTS = 12

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

NON_PERFUME = {
    "tester", "testeur", "sample", "mystery box", "gift set", "set regalo",
    "coffret", "bundle", "travel set", "discovery set", "shampoo",
    "shower gel", "body wash", "body lotion", "body cream", "deodorant",
    "aftershave", "after shave", "body spray", "hair mist", "makeup",
    "cosmetics", "skincare", "conditioner",
}


def _clean(value):
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", _clean(value).lower()).strip()


def _price(value):
    if value is None:
        return None
    text = _clean(value)
    m = PRICE_RE.search(text) or re.search(
        r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)", text
    )
    return (m.group(1).replace(".", ",") + " €") if m else None


def _looks_like_product_url(url):
    return bool(url and PRODUCT_URL_RE.match(url))


def _query_tokens(query):
    return [x for x in _norm(query).split() if len(x) > 1 and x != "ml"]


def _matches(name, query):
    tokens = _query_tokens(query)
    hay = set(_norm(name).split())
    return bool(tokens) and all(t in hay for t in tokens)


def _is_non_perfume(name):
    tokens = set(_norm(name).split())
    for marker in NON_PERFUME:
        mt = set(_norm(marker).split())
        if mt and mt.issubset(tokens):
            return True
    return False


def _get(session, url):
    try:
        response = session.get(
            url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True
        )
        if response.status_code in (403, 429):
            response.close()
            return None
        response.raise_for_status()
        return response
    except requests.RequestException:
        return None


def _extract_name(container, anchor):
    candidates = []
    for selector in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title"):
        node = container.select_one(selector) if container else None
        if node:
            candidates.append(node.get_text(" ", strip=True))
    candidates += [anchor.get("title"), anchor.get("aria-label"), anchor.get_text(" ", strip=True)]
    for value in candidates:
        value = _clean(value)
        if value and value.lower() not in {"vedi", "vedi tutto", "acquista", "immagine"}:
            return value
    return ""


def _parse_search_html(html, query):
    soup = BeautifulSoup(html, "html.parser")
    rows = []
    for anchor in soup.find_all("a", href=True):
        url = urljoin(BASE, anchor["href"]).split("#")[0]
        if not _looks_like_product_url(url):
            continue
        node = anchor
        for _ in range(8):
            parent = getattr(node, "parent", None)
            if not parent:
                break
            candidate = parent
            text = _clean(candidate.get_text(" ", strip=True))
            if len(text) <= 1800 and "€" in text:
                node = candidate
                break
            node = candidate
        card = _clean(node.get_text(" ", strip=True))
        name = _extract_name(node, anchor)
        if not name or not _matches(name, query) or _is_non_perfume(name):
            continue
        price_match = PRICE_RE.search(card)
        if not price_match:
            continue
        rows.append({
            "store": STORE,
            "name": name,
            "price": price_match.group(1) + " €",
            "url": url,
        })
    return rows


def _walk_json(obj, query, rows):
    if isinstance(obj, dict):
        low = {str(k).lower(): v for k, v in obj.items()}
        name = next(
            (low[k] for k in ("name", "product_name", "productname", "title", "label")
             if k in low and isinstance(low[k], (str, int, float))),
            None,
        )
        url = next(
            (low[k] for k in ("url", "link", "product_url", "producturl", "href")
             if k in low and isinstance(low[k], str)),
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
        if (
            name and url and _looks_like_product_url(url)
            and _price(price) and _matches(str(name), query)
            and not _is_non_perfume(str(name))
        ):
            rows.append({
                "store": STORE, "name": str(name),
                "price": _price(price), "url": url.split("#")[0],
            })
        for value in obj.values():
            _walk_json(value, query, rows)
    elif isinstance(obj, list):
        for value in obj:
            _walk_json(value, query, rows)


def _parse_product_page(html, expected_name):
    soup = BeautifulSoup(html, "html.parser")
    expected = set(_norm(expected_name).split())

    # Prefer the Product JSON-LD whose name belongs to this exact product.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop()
            if isinstance(obj, dict):
                typ = obj.get("@type")
                types = typ if isinstance(typ, list) else [typ]
                name = _clean(obj.get("name"))
                if any(str(t).lower() == "product" for t in types) and name:
                    if expected and not expected.issubset(set(_norm(name).split())):
                        continue
                    for key in ("size", "volume", "netContent", "capacity", "contentVolume"):
                        value = obj.get(key)
                        if value:
                            m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", str(value), re.I)
                            if m:
                                return m.group(1)
                    m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", name, re.I)
                    if m:
                        return m.group(1)
                for child in obj.values():
                    if isinstance(child, (dict, list)):
                        stack.append(child)
            elif isinstance(obj, list):
                stack.extend(x for x in obj if isinstance(x, (dict, list)))

    # Next, use the product title / headings and their local block only.
    for selector in ("h1", "h2", "h3", '[itemprop="name"]', 'meta[property="og:title"]'):
        node = soup.select_one(selector)
        if not node:
            continue
        text = _clean(node.get("content") if node.name == "meta" else node.get_text(" ", strip=True))
        m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", text, re.I)
        if m:
            return m.group(1)
        parent = node.parent
        for _ in range(5):
            if not parent:
                break
            block = _clean(parent.get_text(" ", strip=True))
            if len(block) <= 700:
                m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", block, re.I)
                if m:
                    return m.group(1)
            parent = getattr(parent, "parent", None)

    return ""


def _enrich(session, rows):
    out, seen_urls = [], set()
    for row in rows:
        url = row["url"].split("?")[0]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        item = dict(row)
        response = _get(session, url)
        if response:
            try:
                size = _parse_product_page(response.text, item["name"])
            finally:
                response.close()
            if size:
                item["size_ml"] = size
        out.append(item)
    return out


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        # Initialize cookies without relying on a special product.
        home = _get(session, BASE + "/it/")
        if home:
            home.close()

        urls = [
            BASE + "/it/ricerca?search_query=" + quote_plus(query),
            BASE + "/it/ricerca?s=" + quote_plus(query),
            BASE + "/it/ricerca_old?s=" + quote_plus(query),
            BASE + "/it/ricerca_old?search_query=" + quote_plus(query),
        ]

        rows = []
        for url in urls:
            response = _get(session, url)
            if not response:
                continue
            try:
                html = response.text
            finally:
                response.close()
            parsed = _parse_search_html(html, query)
            rows.extend(parsed)
            if parsed:
                break

        if not rows:
            ajax = BASE + "/modules/ecelastic/ajax.php"
            for payload in (
                {"q": query, "query": query, "search_query": query, "id_lang": 5, "id_country": 10, "id_currency": 1},
                {"s": query, "search_query": query, "id_lang": 5, "id_country": 10, "id_currency": 1},
                {"query": query, "id_lang": 5, "id_country": 10, "id_currency": 1},
            ):
                for method in ("get", "post"):
                    try:
                        response = (
                            session.get(ajax, params=payload, headers=HEADERS, timeout=TIMEOUT)
                            if method == "get"
                            else session.post(
                                ajax, data=payload,
                                headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                                timeout=TIMEOUT,
                            )
                        )
                        if response.status_code in (403, 429):
                            response.close()
                            continue
                        raw = response.text
                        response.close()
                        try:
                            data = json.loads(raw)
                            parsed = []
                            _walk_json(data, query, parsed)
                        except Exception:
                            parsed = _parse_search_html(raw, query)
                        rows.extend(parsed)
                    except requests.RequestException:
                        continue
                if rows:
                    break

        # Generic fallback: discover perfume-category links from the site itself.
        if not rows:
            home = _get(session, BASE + "/it/")
            if home:
                soup = BeautifulSoup(home.text, "html.parser")
                categories = []
                for a in soup.find_all("a", href=True):
                    href = urljoin(BASE, a["href"]).split("?")[0]
                    text = _clean(a.get_text(" ", strip=True))
                    if "/it/" in href and ("profum" in _norm(text) or "perfume" in _norm(text)):
                        if href not in categories and not _looks_like_product_url(href):
                            categories.append(href)
                home.close()
                for category in categories[:12]:
                    response = _get(session, category)
                    if not response:
                        continue
                    try:
                        parsed = _parse_search_html(response.text, query)
                    finally:
                        response.close()
                    if parsed:
                        rows.extend(parsed)
                        break

        return _enrich(session, rows[:20])
    finally:
        session.close()


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    print(json.dumps(search(" ".join(sys.argv[1:]) or "Dior"), ensure_ascii=False, indent=2))
