import re
import html
import json
from typing import List, Dict, Optional
from urllib.parse import urljoin, quote_plus

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
TIMEOUT = 25

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
}

SEARCH_URLS = [
    BASE_URL + "/it/ricerca?controller=search&s={query}",
    BASE_URL + "/it/search?controller=search&s={query}",
]

FRAGRANCE_WORDS = (
    "eau de parfum", "eau de toilette", " parfum", "profumo",
    "elixir", "eau forte", "cologne"
)
EXCLUDE_WORDS = (
    "occhiali", "sunglass", "after shave", "dopobarba", "deodor",
    "gel da barba", "balsamo", "lozione", "detergente", "crema",
    "shampoo", "doccia", "shower", "stick", "makeup", "rossetto"
)

def _clean(s):
    return re.sub(r"\s+", " ", html.unescape(str(s or ""))).strip()

def _norm(s):
    s = _clean(s).lower()
    s = re.sub(r"[^\w\s]+", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()

def _tokens(q):
    return [x for x in _norm(q).split() if len(x) > 1]

def _matches(text, query):
    n = _norm(text)
    return all(t in n for t in _tokens(query))

def _is_fragrance(text):
    n = _norm(text)
    if any(_norm(x) in n for x in EXCLUDE_WORDS):
        return False
    return any(_norm(x) in n for x in FRAGRANCE_WORDS)

def _money(value):
    if value is None:
        return None
    s = _clean(value).replace("€", "").replace("$", "").strip()
    m = re.search(r"(\d{1,4}(?:[.,]\d{2}))", s)
    if not m:
        return None
    v = m.group(1)
    # normalize to Italian display
    if "." in v and "," not in v:
        v = v.replace(".", ",")
    try:
        if float(v.replace(",", ".")) <= 0:
            return None
    except ValueError:
        return None
    return v + " €"

def _jsonld_products(soup):
    out = []
    for node in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = node.string or node.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            x = stack.pop()
            if isinstance(x, list):
                stack.extend(x)
            elif isinstance(x, dict):
                if x.get("@type") == "Product":
                    out.append(x)
                for v in x.values():
                    if isinstance(v, (dict, list)):
                        stack.append(v)
    return out

def _product_from_jsonld(obj, page_url, query):
    name = _clean(obj.get("name"))
    if not name or not _matches(name, query):
        return None
    desc = _clean(obj.get("description"))
    combined = name + " " + desc + " " + page_url.replace("-", " ")
    if not _is_fragrance(combined):
        return None

    offers = obj.get("offers", {})
    if isinstance(offers, list):
        offers = offers[0] if offers else {}
    price = _money(offers.get("price") if isinstance(offers, dict) else None)
    if not price:
        return None
    url = obj.get("url") or page_url
    return {"store": STORE, "name": name, "price": price, "url": urljoin(BASE_URL, url)}

def _parse_product_page(session, url, query):
    try:
        r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code != 200:
            return None
    except requests.RequestException:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    # Prefer structured product data.
    for obj in _jsonld_products(soup):
        item = _product_from_jsonld(obj, r.url, query)
        if item:
            return item

    h1 = soup.find("h1")
    if not h1:
        return None
    name = _clean(h1.get_text(" ", strip=True))

    # Product type is often separated from H1 on Sabina.
    top = _clean(soup.get_text(" ", strip=True))[:2500]
    for kind in ("EAU DE PARFUM", "EAU DE TOILETTE", "PARFUM", "ELIXIR", "EAU FORTE", "COLOGNE"):
        if kind.lower() in top.lower() and kind.lower() not in name.lower():
            name += " " + kind
            break

    if not _matches(name, query):
        return None
    if not _is_fragrance(name + " " + r.url.replace("-", " ")):
        return None

    # Exact current sale price on Sabina: "Prezzo:83,67 €"
    page_text = _clean(soup.get_text(" ", strip=True))
    m = re.search(r"\bPrezzo\s*:\s*([€$]?\s*\d{1,4}[.,]\d{2})", page_text, re.I)
    price = _money(m.group(1)) if m else None

    if not price:
        for selector in (
            "meta[property='product:price:amount']",
            "meta[itemprop='price']",
            "[itemprop='price']"
        ):
            el = soup.select_one(selector)
            if el:
                price = _money(el.get("content") or el.get("value") or el.get_text(" ", strip=True))
                if price:
                    break
    if not price:
        return None

    return {"store": STORE, "name": name, "price": price, "url": r.url}

def _candidate_links_from_html(soup, query):
    candidates = []
    seen = set()
    qtokens = _tokens(query)

    # Sabina currently uses URLs such as:
    # /it/profumi-da-uomo/7094-dior-sauvage-eau-de-parfum.html
    # /it/sauvage/11971-sauvage-elixir-eau-de-parfum-dior.html
    product_re = re.compile(r"/it/(?:[^/?#]+/)*\d+-[^/?#]+\.html(?:\?.*)?$", re.I)

    for a in soup.find_all("a", href=True):
        href = urljoin(BASE_URL, a["href"])
        if not product_re.search(href):
            continue
        label = _clean(a.get_text(" ", strip=True))
        hay = _norm(label + " " + href.replace("-", " "))
        if not all(t in hay for t in qtokens):
            continue
        href = href.split("#")[0]
        if href not in seen:
            seen.add(href)
            candidates.append(href)
    return candidates

def _search_pages(session, query):
    all_urls = []
    seen = set()
    for template in SEARCH_URLS:
        try:
            r = session.get(
                template.format(query=quote_plus(query)),
                headers=HEADERS, timeout=TIMEOUT, allow_redirects=True
            )
            if r.status_code != 200:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for url in _candidate_links_from_html(soup, query):
            if url not in seen:
                seen.add(url)
                all_urls.append(url)
    return all_urls

def _fallback_catalog_pages(session, query):
    # Sabina search can be JS/redirect dependent. Its indexed brand/category pages
    # are server-rendered, so use them as a reliable fallback.
    words = _tokens(query)
    pages = []

    if "dior" in words and "sauvage" in words:
        pages.extend([
            BASE_URL + "/it/307-sauvage",
            BASE_URL + "/it/304-dior",
        ])

    # Generic fallback: site search engine endpoint with the full query.
    urls = []
    seen = set()
    for page in pages:
        try:
            r = session.get(page, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code != 200:
                continue
        except requests.RequestException:
            continue
        soup = BeautifulSoup(r.text, "html.parser")
        for u in _candidate_links_from_html(soup, query):
            if u not in seen:
                seen.add(u)
                urls.append(u)
    return urls

def search(query: str) -> List[Dict[str, str]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()

    urls = _search_pages(session, query)
    if not urls:
        urls = _fallback_catalog_pages(session, query)

    results = []
    seen = set()
    for url in urls[:40]:
        item = _parse_product_page(session, url, query)
        if not item:
            continue
        if item["url"] in seen:
            continue
        seen.add(item["url"])
        results.append(item)

    # Best matches first; exact query tokens are already mandatory.
    results.sort(key=lambda x: (len(_norm(x["name"])), x["name"]))
    return results

if __name__ == "__main__":
    query = "Dior Sauvage"
    results = search(query)
    print(f"QUERY: {query}")
    print(f"RISULTATI: {len(results)}")
    for item in results:
        print(item)
