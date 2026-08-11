import json
import re
import html
from typing import List, Dict, Optional
from urllib.parse import quote_plus, urljoin, urlparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup


STORE = "Orioudh"
BASE_URL = "https://orioudh.com"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,it;q=0.8",
}


def _clean(v) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(v or ""))).strip()


def _norm(v) -> str:
    s = _clean(v).lower()
    s = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", s)
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(q: str):
    return [x for x in _norm(q).split() if x]


def _token_match(q: str, p: str) -> bool:
    if q == p:
        return True

    # Gestisce genericamente 9 -> 900 negli slug Shopify.
    if q.isdigit() and p.isdigit():
        return (
            len(p) > len(q)
            and p.startswith(q)
            and set(p[len(q):]) == {"0"}
        )

    return False


def _matches(text: str, query: str) -> bool:
    product_tokens = _tokens(text)
    query_tokens = _tokens(query)

    return bool(query_tokens) and all(
        any(_token_match(q, p) for p in product_tokens)
        for q in query_tokens
    )


def _price(v) -> Optional[str]:
    if v is None:
        return None

    s = _clean(v).replace("€", "").strip()
    m = re.search(r"(\d+(?:[.,]\d{1,2})?)", s)

    if not m:
        return None

    try:
        x = float(m.group(1).replace(",", "."))
    except ValueError:
        return None

    if x <= 0:
        return None

    return f"{x:.2f}".replace(".", ",") + " €"


def _url(v) -> str:
    return urljoin(BASE_URL, str(v or "")).split("?")[0].rstrip("/")


def _path(v) -> str:
    return urlparse(v).path.rstrip("/").lower()


def _predictive(session, query: str) -> List[str]:
    try:
        r = session.get(
            BASE_URL + "/search/suggest.json",
            params={
                "q": query,
                "resources[type]": "product",
                "resources[options][unavailable_products]": "show",
                "resources[limit]": "20",
            },
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if r.status_code != 200:
            return []

        data = r.json()
        products = (
            data.get("resources", {})
            .get("results", {})
            .get("products", [])
        )

        out = []

        for p in products:
            if not isinstance(p, dict):
                continue

            title = _clean(p.get("title"))
            u = _url(p.get("url"))

            if "/products/" in u and _matches(title, query):
                out.append(u)

        return out

    except (requests.RequestException, ValueError, TypeError):
        return []


def _search_html(session, query: str) -> List[str]:
    try:
        r = session.get(
            BASE_URL + "/search",
            params={"q": query, "type": "product"},
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if r.status_code != 200:
            return []

    except requests.RequestException:
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    out = []

    for a in soup.select('a[href*="/products/"]'):
        u = _url(a.get("href"))

        if "/products/" not in u:
            continue

        title = _clean(
            a.get("title")
            or a.get("aria-label")
            or a.get_text(" ", strip=True)
        )

        if _matches(title, query):
            out.append(u)

    return out


def _sitemap_products(session) -> List[str]:
    """
    Fallback costoso: usato SOLO se predictive + search HTML
    non hanno trovato nessun candidato.
    """
    urls = set()

    candidates = [
        BASE_URL + "/sitemap_products_1.xml",
        BASE_URL + "/sitemap.xml",
    ]

    for sitemap in candidates:
        try:
            r = session.get(
                sitemap,
                headers=HEADERS,
                timeout=TIMEOUT,
            )

            if r.status_code != 200:
                continue

            root = ET.fromstring(r.content)

        except (requests.RequestException, ET.ParseError):
            continue

        tag = root.tag.lower()

        if tag.endswith("urlset"):
            for loc in root.findall(".//{*}loc"):
                value = _clean(loc.text)
                if "/products/" in value:
                    urls.add(_url(value))

            if urls:
                return list(urls)

        if tag.endswith("sitemapindex"):
            children = []

            for loc in root.findall(".//{*}loc"):
                value = _clean(loc.text)
                if "sitemap_products_" in value:
                    children.append(value)

            for child in children:
                try:
                    rr = session.get(
                        child,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                    )

                    if rr.status_code != 200:
                        continue

                    child_root = ET.fromstring(rr.content)

                    for loc in child_root.findall(".//{*}loc"):
                        value = _clean(loc.text)
                        if "/products/" in value:
                            urls.add(_url(value))

                except (requests.RequestException, ET.ParseError):
                    continue

            if urls:
                return list(urls)

    return list(urls)


def _sitemap_candidates(session, query: str) -> List[str]:
    q = _tokens(query)
    if not q:
        return []

    out = []

    for u in _sitemap_products(session):
        slug = _norm(
            urlparse(u).path.rsplit("/", 1)[-1]
        )

        if _matches(slug, query):
            out.append(u)

    return out


def _product_json(session, url: str) -> Optional[Dict]:
    try:
        r = session.get(
            _url(url) + ".js",
            headers=HEADERS,
            timeout=TIMEOUT,
        )

        if r.status_code != 200:
            return None

        data = r.json()
        return data if isinstance(data, dict) else None

    except (requests.RequestException, ValueError):
        return None


def _make_product(
    data: Dict,
    url: str,
    query: str,
) -> Optional[Dict]:
    title = _clean(data.get("title"))

    if not title or not _matches(title, query):
        return None

    variants = data.get("variants") or []
    if not isinstance(variants, list):
        variants = []

    available = [
        v for v in variants
        if isinstance(v, dict) and v.get("available") is True
    ]

    pool = available or [
        v for v in variants
        if isinstance(v, dict)
    ]

    prices = []

    for v in pool:
        value = v.get("price")

        try:
            number = float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            continue

        # Shopify product.js normalmente usa valori decimali.
        if number >= 10000:
            number /= 100

        if number > 0:
            prices.append(number)

    price = ""
    if prices:
        price = f"{min(prices):.2f}".replace(".", ",") + " €"

    if not price:
        price = _price(data.get("price")) or ""

    is_available = bool(available)

    return {
        "store": STORE,
        "name": title,
        "price": price,
        "url": _url(url),
        "available": is_available,
        "availability": (
            "in_stock" if is_available else "out_of_stock"
        ),
        "stock_status": (
            "in_stock" if is_available else "out_of_stock"
        ),
    }


def search(query: str) -> List[Dict]:
    query = _clean(query)

    if not query:
        return []

    session = requests.Session()
    candidates = []
    seen = set()

    def add(urls):
        for u in urls:
            u = _url(u)

            if "/products/" not in u:
                continue

            key = _path(u)

            if key in seen:
                continue

            seen.add(key)
            candidates.append(u)

    # Primo passaggio: una sola query precisa.
    add(_predictive(session, query))
    add(_search_html(session, query))

    # Secondo passaggio leggero solo se il primo non trova nulla.
    if not candidates:
        compact = re.sub(
            r"(?<=\d)\s+(?=[a-z])|(?<=[a-z])\s+(?=\d)",
            "",
            _norm(query),
        )

        if compact != _norm(query):
            add(_predictive(session, compact))
            add(_search_html(session, compact))

    # SOLO ora usiamo il sitemap. Non viene più eseguito ogni volta.
    if not candidates:
        add(_sitemap_candidates(session, query))

    results = []
    seen_results = set()

    for u in candidates:
        data = _product_json(session, u)

        if not data:
            continue

        item = _make_product(data, u, query)

        if not item:
            continue

        key = _path(item["url"])

        if key in seen_results:
            continue

        seen_results.add(key)
        results.append(item)

    return results


if __name__ == "__main__":
    for q in ("9 PM", "9 PM Rebel", "9 PM Pour Femme"):
        print("\nQUERY:", q)
        for item in search(q):
            print(item)
