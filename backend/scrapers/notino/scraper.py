from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
GOOGLE_URL = "https://www.google.com/search"
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 20
READER_TIMEOUT = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
READER_HEADERS = {
    "User-Agent": "ScentHunter/1.0",
    "Accept": "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}

PRODUCT_RE = re.compile(r"/p-\d+(?:/|$)", re.I)
PRODUCT_URL_RE = re.compile(
    r"https?://(?:www\.)?notino\.fr/[^\s)\]>\"']+/p-\d+(?:/|\b)", re.I
)
PRICE_RE = re.compile(
    r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)", re.I
)
RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)
CHALLENGE_MARKERS = (
    "just a moment", "cf-chl-", "challenge-platform",
    "checking your browser", "verify you are human",
    "enable javascript and cookies", "vérification de sécurité en cours",
)
OUT_STOCK_MARKERS = (
    "en rupture de stock", "rupture de stock",
    "actuellement indisponible", "produit indisponible",
)

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "set", "discovery set", "fragrance set",
    "perfume set", "parfum set", "coffret", "bundle", "pack",
    "travel set", "kit", "duo", "trio", "mystery box", "tester",
    "testeur", "sample", "shampoo", "shower gel", "body wash",
    "body lotion", "body cream", "body milk", "deodorant", "deo spray",
    "aftershave", "after shave", "body spray", "hair mist", "makeup",
    "cosmetics", "cosmetic", "skincare", "skin care", "cosmetici",
}


def _clean(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"([a-zà-ÿ])([A-ZÀ-Ÿ])", r"\1 \2", text)


def _product_norm(value: Any) -> str:
    value = str(value or "").lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _has_non_perfume_marker(value: Any) -> bool:
    tokens = set(_product_norm(value).split())
    return any(
        set(_product_norm(marker).split()).issubset(tokens)
        for marker in NON_PERFUME_MARKERS
        if _product_norm(marker)
    )


def _tokens(value: Any) -> List[str]:
    return [token for token in _product_norm(value).split() if len(token) > 1]


def _matches(text: Any, query: Any) -> bool:
    text_tokens = set(_product_norm(text).split())
    query_tokens = _tokens(query)
    return bool(query_tokens) and all(token in text_tokens for token in query_tokens)


def _format_price(value: Any) -> str:
    match = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)", _clean(value))
    if not match:
        return ""
    try:
        number = float(match.group(1).replace(",", "."))
    except ValueError:
        return ""
    return f"{number:.2f}".replace(".", ",") + "€" if number > 0 else ""


def _extract_price(text: Any) -> str:
    matches = list(PRICE_RE.finditer(_clean(text)))
    if not matches:
        return ""
    match = matches[-1]
    return _format_price(match.group(1) or match.group(2))


def _looks_like_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return False
    if not PRODUCT_RE.search(parsed.path):
        return False
    return not any(
        x in parsed.path.lower()
        for x in ("/search", "/panier", "/cart", "/login", "/account", "/avis/", "/magazine")
    )


def _search_urls(query: str) -> List[str]:
    q = quote_plus(query)
    return [f"{SEARCH_URL}?exps={q}", f"{BASE_URL}/search?query={q}"]


def _request(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return response


def _reader_request(session: requests.Session, url: str) -> requests.Response:
    response = session.get(
        READER_BASE + url,
        headers=READER_HEADERS,
        timeout=READER_TIMEOUT,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response


def _is_challenge(text: str) -> bool:
    low = _clean(text).lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


def _clean_name(text: str) -> str:
    value = RATING_RE.sub(" ", _clean(text))
    value = PRICE_RE.sub(" ", value)
    value = re.sub(
        r"^(?:promo|nouveau|discount|cadeaux? offerts|livraison offerte)\s+",
        "", value, flags=re.I,
    )
    words = value.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            value = " ".join(words[:half])
    return _clean(value)


def _card_text(link) -> str:
    node = link
    best = _clean(link.get_text(" ", strip=True))
    for _ in range(10):
        node = getattr(node, "parent", None)
        if node is None:
            break
        text = _clean(node.get_text(" ", strip=True))
        if len(text) > len(best):
            best = text
        if 40 <= len(text) <= 1200 and _extract_price(text):
            return text
    return best


def _candidate_anchor(link, container) -> str:
    values = [
        link.get("title"),
        link.get("aria-label"),
        link.get("data-testid"),
        link.get_text(" ", strip=True),
    ]
    image = link.find("img")
    if image:
        values.extend([image.get("alt"), image.get("title")])
    for selector in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title"):
        element = container.select_one(selector)
        if element:
            values.append(element.get_text(" ", strip=True))
    for value in values:
        cleaned = _clean(value)
        if cleaned and cleaned.lower() not in {"voir", "voir tout", "acheter", "image"}:
            return cleaned
    return ""


def _make_candidate(url: str, anchor: str, card: str, query: str, source: str) -> Optional[Dict[str, Any]]:
    url = _clean(url).split("?")[0]
    if not _looks_like_product_url(url):
        return None
    anchor = _clean(anchor)
    card = _clean(card)
    name = _clean_name(anchor)
    if not name or _has_non_perfume_marker(name):
        return None
    query_tokens = _tokens(query)
    name_tokens = set(_product_norm(name).split())
    if not query_tokens or not all(token in name_tokens for token in query_tokens):
        return None
    hits = {token: token in name_tokens for token in query_tokens}
    score = sum(hits.values()) * 5
    if all(hits.values()):
        score += 5
    if _extract_price(anchor) or _extract_price(card):
        score += 1
    return {
        "url": url,
        "anchor_text": anchor or name,
        "card_text": card or anchor,
        "name": name,
        "score": score,
        "token_hits": hits,
        "contains_all_query_tokens": all(hits.values()),
        "source": source,
    }


def extract_candidates_from_html(html: str, query: str) -> List[Dict[str, Any]]:
    soup = BeautifulSoup(html or "", "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    for link in soup.find_all("a", href=True):
        url = urljoin(BASE_URL, _clean(link.get("href"))).split("?")[0]
        if not _looks_like_product_url(url):
            continue
        card = _card_text(link)
        anchor = _candidate_anchor(link, BeautifulSoup(str(link.parent), "html.parser") if link.parent else link)
        candidate = _make_candidate(url, anchor, card, query, "direct-search")
        if candidate and (url not in found or candidate["score"] > found[url]["score"]):
            found[url] = candidate
    return sorted(found.values(), key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]))


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    markdown = re.compile(r"\[([^\]]+)\]\((https?://(?:www\.)?notino\.fr/[^)]+)\)", re.I)
    for index, line in enumerate(lines):
        for match in markdown.finditer(line):
            url = _clean(match.group(2)).split("?")[0]
            anchor = _clean(match.group(1))
            context = _clean(" ".join(lines[max(0, index - 1):min(len(lines), index + 2)]))
            candidate = _make_candidate(url, anchor, context, query, "reader-search")
            if candidate and (url not in found or candidate["score"] > found[url]["score"]):
                found[url] = candidate
    for match in PRODUCT_URL_RE.finditer(text or ""):
        url = match.group(0).split("?")[0].rstrip(".,")
        if url in found:
            continue
        context = _clean((text or "")[max(0, match.start() - 260):match.end() + 260])
        candidate = _make_candidate(url, "", context, query, "reader-url")
        if candidate:
            found[url] = candidate
    return sorted(found.values(), key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]))


def _reader_discovery(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    found: Dict[str, Dict[str, Any]] = {}
    pages = []
    for url in _search_urls(query):
        try:
            response = _reader_request(session, url)
            candidates = _reader_candidates(response.text, query)
            for candidate in candidates:
                old = found.get(candidate["url"])
                if old is None or candidate["score"] > old["score"]:
                    found[candidate["url"]] = candidate
            pages.append({"url": url, "status": response.status_code, "candidate_count": len(candidates), "reader": True})
            if candidates:
                break
        except requests.RequestException as exc:
            pages.append({"url": url, "status": None, "error": f"{type(exc).__name__}: {exc}", "reader": True})
    ordered = sorted(found.values(), key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]))
    return ordered, {"query": query, "pages": pages, "candidate_count": len(ordered), "fallback": "jina-reader"}


def _google_discovery(query: str, session: requests.Session) -> List[Dict[str, Any]]:
    try:
        response = session.get(
            GOOGLE_URL,
            params={"q": f'site:notino.fr "{query}"'},
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
    except requests.RequestException:
        return []
    soup = BeautifulSoup(response.text or "", "html.parser")
    found: Dict[str, Dict[str, Any]] = {}
    for link in soup.find_all("a", href=True):
        href = _clean(link.get("href"))
        match = re.search(
            r"https?://(?:www\.)?notino\.fr/[^\s&<>\"']+/p-\d+(?:/|\b)",
            href, re.I,
        )
        if not match:
            continue
        url = match.group(0).split("?")[0].rstrip("/.,")
        anchor = _clean(link.get_text(" ", strip=True))
        card = _card_text(link)
        candidate = _make_candidate(url, anchor, card, query, "google-site-discovery")
        if candidate:
            old = found.get(url)
            if old is None or candidate["score"] > old["score"]:
                found[url] = candidate
    return sorted(found.values(), key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]))


def _search_http_candidates(query: str, session: requests.Session) -> List[Dict[str, Any]]:
    candidates: Dict[str, Dict[str, Any]] = {}
    for url in _search_urls(query):
        try:
            response = _request(session, url)
        except requests.RequestException:
            continue
        for candidate in extract_candidates_from_html(response.text, query):
            old = candidates.get(candidate["url"])
            if old is None or candidate["score"] > old["score"]:
                candidates[candidate["url"]] = candidate
        if candidates:
            break
    ordered = sorted(candidates.values(), key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]))
    if ordered:
        return ordered
    reader_candidates, _ = _reader_discovery(query, session)
    if reader_candidates:
        return reader_candidates
    return _google_discovery(query, session)


def _json_ld_products(soup: BeautifulSoup) -> Iterable[Dict[str, Any]]:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                if isinstance(item.get("@graph"), list):
                    stack.extend(item["@graph"])
                types = item.get("@type", [])
                types = types if isinstance(types, list) else [types]
                if "Product" in types:
                    yield item


def _offer_price(offers: Any) -> str:
    values = offers if isinstance(offers, list) else [offers] if isinstance(offers, dict) else []
    for offer in values:
        if not isinstance(offer, dict):
            continue
        availability = _clean(offer.get("availability")).lower()
        if any(x in availability for x in ("outofstock", "soldout", "discontinued")):
            continue
        price = _format_price(offer.get("price")) or _format_price(offer.get("lowPrice"))
        if price:
            return price
    return ""


def _reader_product(text: str, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    content = _clean(text)
    name = ""
    for line in [re.sub(r"^#+\s*", "", x).strip() for x in (text or "").splitlines() if x.strip()][:120]:
        line = _clean(line)
        if _matches(line, query) and len(line) <= 220 and not PRICE_RE.search(line):
            candidate_name = _clean_name(line)
            if candidate_name and not _has_non_perfume_marker(candidate_name):
                name = candidate_name
                break
    if not name:
        name = _clean_name(candidate.get("anchor_text") or "")
    if not name or _has_non_perfume_marker(name):
        return None
    if not _matches(name, query):
        return None
    price = ""
    current = re.search(r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€", content, re.I)
    if current:
        price = _format_price(current.group(1))
    if not price:
        stock = re.search(r"en\s+stock[^€]{0,120}?(\d{1,4}[.,]\d{2})\s*€", content, re.I)
        if stock:
            price = _format_price(stock.group(1))
    if not price:
        price = _extract_price(candidate.get("anchor_text", "")) or _extract_price(candidate.get("card_text", ""))
    if not price:
        return None
    return {"store": STORE, "name": name, "price": price, "url": candidate["url"]}


def _product_details(session: requests.Session, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    url = candidate["url"]
    try:
        response = _request(session, url)
    except requests.RequestException:
        try:
            return _reader_product(_reader_request(session, url).text, candidate, query)
        except requests.RequestException:
            return None
    final_url = response.url.split("?")[0]
    if _is_challenge(response.text) or not _looks_like_product_url(final_url):
        try:
            return _reader_product(_reader_request(session, url).text, candidate, query)
        except requests.RequestException:
            return None
    soup = BeautifulSoup(response.text, "html.parser")
    name = price = ""
    for product in _json_ld_products(soup):
        product_name = _clean(product.get("name"))
        brand = product.get("brand")
        brand = _clean(brand.get("name")) if isinstance(brand, dict) else _clean(brand)
        if product_name and _matches(f"{brand} {product_name}", query) and not _has_non_perfume_marker(product_name):
            product_price = _offer_price(product.get("offers"))
            if product_price:
                name, price = product_name, product_price
                break
    page_text = _clean(soup.get_text(" ", strip=True))
    if not name:
        h1 = soup.find("h1")
        if h1:
            candidate_name = _clean(h1.get_text(" ", strip=True))
            if _matches(candidate_name, query) and not _has_non_perfume_marker(candidate_name):
                name = candidate_name
    if not name:
        title = soup.find("title")
        if title:
            candidate_name = _clean(title.get_text(" ", strip=True)).split("|")[0]
            if _matches(candidate_name, query) and not _has_non_perfume_marker(candidate_name):
                name = candidate_name
    if not name:
        return None
    if not price:
        m = re.search(r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€", page_text, re.I)
        if m:
            price = _format_price(m.group(1))
    if not price:
        m = re.search(r"en\s+stock\s*[|:]?\s*(\d{1,4}[.,]\d{2})\s*€", page_text, re.I)
        if m:
            price = _format_price(m.group(1))
    if not price:
        price = _extract_price(candidate.get("anchor_text", "")) or _extract_price(candidate.get("card_text", ""))
    if not price:
        return None
    low = page_text.lower()
    if any(marker in low for marker in OUT_STOCK_MARKERS) and not any(marker in low for marker in ("en stock", "ajouter au panier", "add to cart")):
        return None
    return {"store": STORE, "name": name, "price": price, "url": final_url}


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        candidates = _search_http_candidates(query, session)
        results: List[Dict[str, Any]] = []
        seen = set()
        for candidate in candidates:
            result = _product_details(session, candidate, query)
            if not result:
                continue
            key = (result.get("url", "") + "|" + _clean(result.get("name"))).lower()
            if key in seen:
                continue
            seen.add(key)
            results.append(result)
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
