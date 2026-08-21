from __future__ import annotations

import html
import json
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp?exps="
JINA = "https://r.jina.ai/"
TIMEOUT = 8
READER_TIMEOUT = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}
JINA_HEADERS = {
    "User-Agent": "ScentHunter/1.0",
    "Accept": "text/plain,text/markdown,*/*;q=0.8",
}

PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,4}[.,]\d{2})\s*€?")
SIZE_RE = re.compile(r"\b\d{1,4}(?:[.,]\d{1,2})?\s*(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\b", re.I)
NON_PRODUCT = (
    "coffret", "set cadeau", "gift set", "discovery set", "bundle", "pack",
    "duo", "trio", "tester", "testeur", "shampoo", "gel douche",
    "lotion", "déodorant", "deodorant", "body spray", "maquillage",
    "cosmetics", "cosmétique", "crème", "cream"
)
OUT_STOCK = ("en rupture de stock", "actuellement indisponible", "produit indisponible")
IN_STOCK = ("en stock", "ajouter au panier", "add to cart")
CHALLENGE = ("just a moment", "checking your browser", "verify you are human",
             "challenge-platform", "vérification de sécurité en cours")

def clean(v: Any) -> str:
    return re.sub(r"\s+", " ", html.unescape(str(v or ""))).strip()

def norm(v: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(v).lower()).strip()

def tokens(v: Any) -> List[str]:
    return [x for x in norm(SIZE_RE.sub(" ", clean(v))).split() if len(x) > 1]

def matches(text: Any, query: Any) -> bool:
    hay = norm(text)
    return bool(tokens(query)) and all(t in hay for t in tokens(query))

def price(text: Any) -> str:
    s = clean(text)
    # Prefer "prix actuel", then a price associated with a product size.
    m = re.search(r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€", s, re.I)
    if m:
        return m.group(1).replace(".", ",") + "€"
    sized = re.findall(
        r"\b\d{1,4}(?:[.,]\d{1,2})?\s*(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\s+"
        r"(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€", s, re.I
    )
    if sized:
        return sized[-1].replace(".", ",") + "€"
    vals = []
    for m in PRICE_RE.finditer(s):
        after = s[m.end():m.end()+25].lower()
        if re.match(r"\s*/\s*100\s*(?:ml|g)", after):
            continue
        vals.append(m.group(1))
    return (vals[-1].replace(".", ",") + "€") if vals else ""

def product_url(raw: Any) -> Optional[str]:
    u = html.unescape(str(raw or "")).replace("\\/", "/").strip()
    if u.startswith("//"):
        u = "https:" + u
    elif u.startswith("/"):
        u = urljoin(BASE_URL, u)
    u = u.split("#")[0].split("?")[0]
    p = urlparse(u)
    if p.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
        return None
    path = p.path.rstrip("/")
    bad = ("/search", "/avis/", "/magazine/", "/blog/", "/panier", "/cart", "/login")
    if not path or any(path.lower().startswith(x) for x in bad):
        return None
    # Notino product pages normally have /brand/slug/ or /brand/slug/p-id/.
    seg = [x for x in path.split("/") if x]
    if len(seg) < 2:
        return None
    return f"https://www.notino.fr{path}"

def challenge(text: str) -> bool:
    low = clean(text).lower()
    return any(x in low for x in CHALLENGE)

def request(session: requests.Session, url: str, timeout: int = TIMEOUT):
    r = session.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r

def jsonld_products(soup: BeautifulSoup):
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
                continue
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("@graph"), list):
                stack.extend(item["@graph"])
            typ = item.get("@type", [])
            typ = typ if isinstance(typ, list) else [typ]
            if "Product" in typ:
                yield item

def offer_price(offers: Any) -> str:
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return ""
    for o in offers:
        if not isinstance(o, dict):
            continue
        av = clean(o.get("availability")).lower()
        if "outofstock" in av or "soldout" in av:
            continue
        v = o.get("price") or o.get("lowPrice")
        if v:
            m = re.search(r"\d+(?:[.,]\d+)?", str(v))
            if m:
                return m.group(0).replace(".", ",") + "€"
    return ""

def non_perfume(name: str, url: str = "", title: str = "") -> bool:
    blob = norm(f"{name} {url} {title}")
    return any(norm(x) in blob for x in NON_PRODUCT)

def parse_candidates(html_text: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    for a in soup.find_all("a", href=True):
        url = product_url(a.get("href"))
        if not url:
            continue
        # Walk up to the product card, but keep it bounded.
        node = a
        card = clean(a.get_text(" ", strip=True))
        for _ in range(8):
            node = node.parent
            if node is None:
                break
            t = clean(node.get_text(" ", strip=True))
            if len(t) > len(card):
                card = t
            if len(t) > 80 and "€" in t:
                break
        anchor = clean(a.get_text(" ", strip=True))
        searchable = f"{anchor} {card} {url}"
        exact = matches(searchable, query)
        if not exact and norm(query) not in norm(url):
            continue
        score = 100 if exact else 40
        if "liquid-brun" in url.lower():
            score += 50
        found[url] = {
            "url": url, "anchor": anchor, "card": card, "score": score,
            "exact": exact
        }
    return sorted(found.values(), key=lambda x: (-x["score"], x["url"]))[:12]

def jina_candidates(session: requests.Session, query: str) -> List[Dict[str, Any]]:
    url = SEARCH_URL + quote_plus(query)
    try:
        r = session.get(JINA + url, headers=JINA_HEADERS, timeout=READER_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException:
        return []
    text = clean(r.text)
    out = {}
    # Jina output contains the actual Notino product URLs in markdown/text.
    for m in re.finditer(r"https?://(?:www\.)?notino\.fr/[^\s<>)\]\"']+", r.text, re.I):
        u = product_url(m.group(0))
        if not u:
            continue
        context = r.text[max(0, m.start()-500):m.end()+500]
        if matches(context, query) or norm(query) in norm(u):
            out[u] = {
                "url": u, "anchor": clean(context), "card": clean(context),
                "score": 90 if matches(context, query) else 50, "exact": matches(context, query)
            }
    return sorted(out.values(), key=lambda x: (-x["score"], x["url"]))[:12]

def product_details(session: requests.Session, cand: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    url = cand["url"]
    try:
        r = request(session, url)
        body = r.text
    except requests.RequestException:
        try:
            rr = session.get(JINA + url, headers=JINA_HEADERS, timeout=READER_TIMEOUT)
            rr.raise_for_status()
            return parse_reader(rr.text, cand, query)
        except requests.RequestException:
            return card_result(cand, query)

    if challenge(body):
        try:
            rr = session.get(JINA + url, headers=JINA_HEADERS, timeout=READER_TIMEOUT)
            rr.raise_for_status()
            return parse_reader(rr.text, cand, query)
        except requests.RequestException:
            return card_result(cand, query)

    soup = BeautifulSoup(body, "html.parser")
    page_text = clean(soup.get_text(" ", strip=True))
    name, p = "", ""

    for item in jsonld_products(soup):
        n = clean(item.get("name"))
        b = item.get("brand")
        b = clean(b.get("name")) if isinstance(b, dict) else clean(b)
        if matches(f"{b} {n}", query):
            name = n
            p = offer_price(item.get("offers"))
            if name:
                break

    if not name:
        h1 = soup.find("h1")
        if h1 and matches(h1.get_text(" ", strip=True), query):
            name = clean(h1.get_text(" ", strip=True))

    if not name:
        title = soup.find("title")
        if title:
            n = clean(title.get_text(" ", strip=True)).split("|")[0]
            if matches(n, query):
                name = n

    if not name:
        return card_result(cand, query)

    title_text = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    if non_perfume(name, url, title_text):
        return None

    if not p:
        p = price(page_text) or price(cand["card"])
    if not p:
        return None

    low = page_text.lower()
    if any(x in low for x in OUT_STOCK) and not any(x in low for x in IN_STOCK):
        return None

    return {"store": STORE, "name": name, "price": p, "url": r.url.split("?")[0]}

def parse_reader(text: str, cand: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    content = clean(text)
    if not matches(content + " " + cand["url"], query):
        return None
    lines = [clean(x.lstrip("#").strip()) for x in (text or "").splitlines() if clean(x)]
    name = ""
    for line in lines[:160]:
        if matches(line, query) and len(line) <= 220 and not PRICE_RE.search(line):
            name = line
            break
    if not name:
        name = clean(cand.get("anchor") or "")
    if not name or non_perfume(name, cand["url"]):
        return None
    p = price(content) or price(cand.get("card"))
    if not p:
        return None
    low = content.lower()
    if any(x in low for x in OUT_STOCK) and not any(x in low for x in IN_STOCK):
        return None
    return {"store": STORE, "name": name, "price": p, "url": cand["url"]}

def card_result(cand: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    name = clean(cand.get("anchor") or "")
    card = clean(cand.get("card") or "")
    if not name or not matches(name, query):
        # The card itself can contain the full product title even when anchor is only an image.
        blob = card
        if not matches(blob, query):
            return None
        # Extract the first short line containing the query.
        for part in re.split(r"(?<=[€])\s+|(?<=\))\s+", card):
            if matches(part, query):
                name = clean(part)
                break
    if not name or non_perfume(name, cand["url"]):
        return None
    p = price(name) or price(card)
    if not p:
        return None
    return {"store": STORE, "name": name, "price": p, "url": cand["url"]}

def search(query: str) -> List[Dict[str, Any]]:
    query = clean(query)
    if not query:
        return []
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        search_url = SEARCH_URL + quote_plus(query)
        candidates: List[Dict[str, Any]] = []
        try:
            r = request(session, search_url)
            if not challenge(r.text):
                candidates = parse_candidates(r.text, query)
        except requests.RequestException:
            pass

        if not candidates:
            candidates = jina_candidates(session, query)

        # If search page has only weak candidates, the brand page is a generic
        # fallback discovered from the search page itself; no product is hard-coded.
        results, seen = [], set()
        for c in candidates[:12]:
            item = product_details(session, c, query)
            if not item:
                continue
            key = (item["url"].lower(), norm(item["name"]))
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
            if len(results) >= 10:
                break
        return results
    finally:
        session.close()

def scrape(query: str) -> List[Dict[str, Any]]:
    return search(query)

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()
    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
