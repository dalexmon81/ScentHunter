from __future__ import annotations

import html as html_lib
import json
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
READER_BASE = "https://r.jina.ai/"
TIMEOUT = 20
READER_TIMEOUT = 12
SCRAPER_VERSION = "notino-FR-generic-discovery-2026-08-19-v3-reader-robust"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
READER_HEADERS = {"User-Agent": "ScentHunter/1.0", "Accept": "text/plain,text/markdown,text/html;q=0.9,*/*;q=0.8", "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7"}

PRODUCT_RE = re.compile(r"/p-\d+(?:/|$)", re.I)
PRODUCT_URL_RE = re.compile(r"https?://(?:www\.)?notino\.fr/[^\s)\]>\"']+/p-\d+(?:/|\b)", re.I)
READER_ABSOLUTE_PRODUCT_RE = re.compile(r"(?:https?:)?(?:\\/\\/|//)(?:www\\?\.)?notino\\?\.fr(?:\\/|/)[^\s<>)\]\\\"']*?/p-\d+(?:\\/|/|\b)", re.I)
READER_RELATIVE_PRODUCT_RE = re.compile(r"/(?:[a-z0-9][^\s<>)\]\\\"']*/)+p-\d+(?:/|\b)", re.I)
PRICE_RE = re.compile(r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)", re.I)
RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)
CHALLENGE_MARKERS = ("just a moment", "cf-chl-", "challenge-platform", "checking your browser", "verify you are human", "enable javascript and cookies", "vérification de sécurité en cours")
IN_STOCK_MARKERS = ("en stock", "ajouter au panier", "add to cart")
OUT_STOCK_MARKERS = ("en rupture de stock", "rupture de stock", "actuellement indisponible", "produit indisponible")

NON_PERFUME_MARKERS = {
    "gift set", "set regalo", "set", "discovery set", "fragrance set", "perfume set", "parfum set",
    "coffret", "bundle", "pack", "travel set", "kit", "duo", "trio", "mystery box", "tester",
    "testeur", "sample", "shampoo", "shower gel", "body wash", "body lotion", "body cream",
    "body milk", "deodorant", "deo spray", "aftershave", "after shave", "body spray", "hair mist",
    "makeup", "cosmetics", "cosmetic", "skincare", "skin care", "cosmetici",
}


def _product_norm(value: Any) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _has_non_perfume_marker(value: Any) -> bool:
    tokens = set(_product_norm(value).split())
    return any(set(_product_norm(marker).split()).issubset(tokens) for marker in NON_PERFUME_MARKERS if _product_norm(marker))


def _clean(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return re.sub(r"([a-zà-ÿ])([A-ZÀ-Ÿ])", r"\1 \2", text)


def _tokens(value: Any) -> List[str]:
    return [x for x in re.findall(r"[a-z0-9]+", _clean(value).lower()) if len(x) > 1]


def _matches(text: Any, query: Any) -> bool:
    text = _clean(text).lower()
    tokens = _tokens(query)
    return bool(tokens) and all(token in text for token in tokens)


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
    m = matches[-1]
    return _format_price(m.group(1) or m.group(2))


def _normalise_reader_url(raw: Any) -> Optional[str]:
    """Normalize URLs emitted by Jina as markdown, HTML or escaped JSON text."""
    value = html_lib.unescape(str(raw or "")).strip()
    value = value.replace("\\/", "/")
    value = value.replace("\\u002F", "/")
    value = unquote(value)
    value = value.strip(" <>\"'()[]{}.,;")
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(BASE_URL, value)
    try:
        parsed = urlparse(value)
    except Exception:
        return None
    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return None
    if not PRODUCT_RE.search(parsed.path):
        return None
    return f"https://{parsed.netloc}{parsed.path.rstrip('/')}"


def _looks_like_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    if parsed.netloc.lower() not in {"www.notino.fr", "notino.fr"} or not PRODUCT_RE.search(parsed.path):
        return False
    return not any(x in parsed.path.lower() for x in ("/search", "/panier", "/cart", "/login", "/account", "/avis/", "/magazine"))


def _search_urls(query: str) -> List[str]:
    q = quote_plus(query)
    return [f"{SEARCH_URL}?exps={q}", f"{BASE_URL}/search?query={q}"]


def _request(session: requests.Session, url: str) -> requests.Response:
    response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return response


def _reader_request(session: requests.Session, url: str) -> requests.Response:
    response = session.get(READER_BASE + url, headers=READER_HEADERS, timeout=READER_TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    return response


def _is_challenge(text: str) -> bool:
    low = _clean(text).lower()
    return any(x in low for x in CHALLENGE_MARKERS)


def _clean_name(text: str) -> str:
    value = RATING_RE.sub(" ", _clean(text))
    value = PRICE_RE.sub(" ", value)
    value = re.sub(r"^(?:promo|nouveau|discount|cadeaux? offerts|livraison offerte)\s+", "", value, flags=re.I)
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


def _make_candidate(url: str, anchor: str, card: str, query: str, source: str) -> Optional[Dict[str, Any]]:
    url = _clean(url).split("?")[0]
    if not _looks_like_product_url(url):
        return None
    anchor = _clean(anchor)
    card = _clean(card)
    name = _clean_name(anchor)
    if not name:
        # For reader output where the link text is omitted, recover the name
        # from the local context instead of rejecting the URL immediately.
        name = _clean_name(card)
    if not name or _has_non_perfume_marker(name):
        return None
    name_tokens = set(_product_norm(name).split())
    query_tokens = _tokens(query)
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
        anchor = _clean(link.get_text(" ", strip=True))
        card = _card_text(link)
        candidate = _make_candidate(url, anchor, card, query, "direct-search")
        if candidate and (candidate["url"] not in found or candidate["score"] > found[candidate["url"]]["score"]):
            found[candidate["url"]] = candidate
    return sorted(found.values(), key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]))


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    """Discover product URLs from Jina output regardless of link representation."""
    found: Dict[str, Dict[str, Any]] = {}
    raw = html_lib.unescape(text or "").replace("\\/", "/")
    lines = [x.strip() for x in raw.splitlines() if x.strip()]

    # Markdown links: absolute or relative Notino URLs.
    markdown = re.compile(r"\[([^\]]+)\]\(([^)]+)\)", re.I)
    for i, line in enumerate(lines):
        for match in markdown.finditer(line):
            anchor = _clean(match.group(1))
            url = _normalise_reader_url(match.group(2))
            if not url:
                continue
            context = _clean(" ".join(lines[max(0, i - 2):min(len(lines), i + 3)]))
            candidate = _make_candidate(url, anchor, context, query, "reader-markdown")
            if candidate and (url not in found or candidate["score"] > found[url]["score"]):
                found[url] = candidate

    # Raw absolute URLs, including escaped JSON-style slashes.
    for pattern in (PRODUCT_URL_RE, READER_ABSOLUTE_PRODUCT_RE, READER_RELATIVE_PRODUCT_RE):
        for match in pattern.finditer(raw):
            url = _normalise_reader_url(match.group(0))
            if not url or url in found:
                continue
            start = max(0, match.start() - 420)
            end = min(len(raw), match.end() + 420)
            context = _clean(raw[start:end])
            candidate = _make_candidate(url, context, context, query, "reader-url")
            if candidate:
                found[url] = candidate

    # HTML fragments or href attributes that Jina may preserve verbatim.
    for match in re.finditer(r"(?:href|url)\s*=\s*[\"']([^\"']+)[\"']", raw, re.I):
        url = _normalise_reader_url(match.group(1))
        if not url or url in found:
            continue
        context = _clean(raw[max(0, match.start() - 420):min(len(raw), match.end() + 420)])
        candidate = _make_candidate(url, context, context, query, "reader-href")
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
            pages.append({"url": url, "reader_url": READER_BASE + url, "status": response.status_code, "html_length": len(response.text or ""), "candidate_count": len(candidates), "reader": True})
            if candidates:
                break
        except requests.RequestException as exc:
            pages.append({"url": url, "reader_url": READER_BASE + url, "status": None, "error": f"{type(exc).__name__}: {exc}", "reader": True})
    ordered = sorted(found.values(), key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]))
    return ordered, {"query": query, "search_urls": _search_urls(query), "pages": pages, "raw_product_urls": len(ordered), "candidate_urls": len(ordered), "raw_query_token_hits": [x for x in ordered if x["contains_all_query_tokens"]], "fallback": "jina-reader"}


def _search_http_candidates(query: str, session: Optional[requests.Session] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    own = session is None
    if own:
        session = requests.Session()
        session.headers.update(HEADERS)
    candidates: Dict[str, Dict[str, Any]] = {}
    pages = []
    try:
        for url in _search_urls(query):
            try:
                response = _request(session, url)
            except requests.RequestException as exc:
                pages.append({"url": url, "status": getattr(getattr(exc, "response", None), "status_code", None), "error": f"{type(exc).__name__}: {exc}"})
                continue
            found = extract_candidates_from_html(response.text, query)
            for candidate in found:
                old = candidates.get(candidate["url"])
                if old is None or candidate["score"] > old["score"]:
                    candidates[candidate["url"]] = candidate
            pages.append({"url": url, "final_url": response.url, "status": response.status_code, "html_length": len(response.text or ""), "candidate_count": len(found), "cloudflare": _is_challenge(response.text), "source": "direct"})
            if found:
                break
        ordered = sorted(candidates.values(), key=lambda x: (not x["contains_all_query_tokens"], -x["score"], x["url"]))
        if ordered:
            return ordered, {"query": query, "search_urls": _search_urls(query), "pages": pages, "raw_product_urls": len(ordered), "candidate_urls": len(ordered), "raw_query_token_hits": [x for x in ordered if x["contains_all_query_tokens"]], "fallback": None}
        reader_candidates, report = _reader_discovery(query, session)
        report["direct_pages"] = pages
        return reader_candidates, report
    finally:
        if own:
            session.close()


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


def _offer_data(offers: Any) -> Tuple[str, str]:
    if isinstance(offers, dict):
        offers = [offers]
    if not isinstance(offers, list):
        return "", ""
    for offer in offers:
        if not isinstance(offer, dict):
            continue
        availability = _clean(offer.get("availability")).lower()
        if any(x in availability for x in ("outofstock", "soldout", "discontinued")):
            continue
        price = _format_price(offer.get("price")) or _format_price(offer.get("lowPrice"))
        if price:
            return price, availability
    return "", ""


def _reader_product(text: str, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    content = _clean(text)
    if not _matches(content + " " + candidate["url"], query):
        return None
    name = ""
    for line in [re.sub(r"^#+\s*", "", x).strip() for x in (text or "").splitlines() if x.strip()][:100]:
        line = _clean(line)
        if _matches(line, query) and len(line) <= 220 and not PRICE_RE.search(line) and not line.lower().startswith(("image", "description", "composition", "avis", "prix actuel")):
            name = _clean_name(line)
            if name:
                break
    if not name:
        name = _clean_name(candidate.get("anchor_text") or candidate.get("card_text", ""))
    if not name or _has_non_perfume_marker(name):
        return None
    query_tokens = _tokens(query)
    name_tokens = set(_product_norm(name).split())
    if not query_tokens or not all(token in name_tokens for token in query_tokens):
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
    low = content.lower()
    if any(x in low for x in OUT_STOCK_MARKERS) and not any(x in low for x in IN_STOCK_MARKERS):
        return None
    return {"store": STORE, "name": name, "price": price, "url": candidate["url"]}


def _card_result(candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    anchor = _clean(candidate.get("anchor_text") or "")
    card = _clean(candidate.get("card_text") or "")
    name = _clean_name(anchor)
    if not name:
        return None
    if _has_non_perfume_marker(name):
        return None
    query_tokens = _tokens(query)
    name_tokens = set(_product_norm(name).split())
    if not query_tokens or not all(token in name_tokens for token in query_tokens):
        return None
    price = _extract_price(anchor) or _extract_price(card)
    if not price:
        return None
    return {"store": STORE, "name": name, "price": price, "url": candidate["url"]}


def _product_details(session: requests.Session, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    url = candidate["url"]
    try:
        response = _request(session, url)
    except requests.RequestException:
        try:
            return _reader_product(_reader_request(session, url).text, candidate, query) or _card_result(candidate, query)
        except requests.RequestException:
            return _card_result(candidate, query)
    final_url = response.url.split("?")[0]
    if _is_challenge(response.text) or not _looks_like_product_url(final_url):
        try:
            return _reader_product(_reader_request(session, url).text, candidate, query) or _card_result(candidate, query)
        except requests.RequestException:
            return _card_result(candidate, query)
    soup = BeautifulSoup(response.text, "html.parser")
    page_text = _clean(soup.get_text(" ", strip=True))
    name = price = ""
    for product in _json_ld_products(soup):
        product_name = _clean(product.get("name"))
        brand = product.get("brand")
        brand = _clean(brand.get("name")) if isinstance(brand, dict) else _clean(brand)
        if _matches(f"{brand} {product_name}", query):
            price, _ = _offer_data(product.get("offers"))
            if product_name and price:
                name = product_name
                break
    if not name:
        h1 = soup.find("h1")
        if h1 and _matches(h1.get_text(" ", strip=True), query):
            name = _clean(h1.get_text(" ", strip=True))
    if not name:
        title = soup.find("title")
        if title:
            candidate_name = _clean(title.get_text(" ", strip=True)).split("|")[0]
            if _matches(candidate_name, query):
                name = candidate_name
    if not name:
        return _card_result(candidate, query)
    if not price:
        m = re.search(r"prix\s+actuel\s+(\d{1,4}[.,]\d{2})\s*€", page_text, re.I)
        if m:
            price = _format_price(m.group(1))
    if not price:
        m = re.search(r"en\s+stock\s*[|:]?\s*(\d{1,4}[.,]\d{2})\s*€", page_text, re.I)
        if m:
            price = _format_price(m.group(1))
    if not price:
        price = _extract_price(candidate.get("anchor_text", "")) or _extract_price(candidate.get("card_text", ""))
    low = page_text.lower()
    if any(x in low for x in OUT_STOCK_MARKERS) and not any(x in low for x in IN_STOCK_MARKERS):
        return None
    return {"store": STORE, "name": name, "price": price, "url": final_url} if price else None


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        candidates, _ = _search_http_candidates(query, session=session)
        results, seen = [], set()
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


def diagnose(query: str) -> Dict[str, Any]:
    query = _clean(query)
    if not query:
        return {"diagnostic": True, "scraper_version": SCRAPER_VERSION, "query": query, "error": "empty_query"}
    session = requests.Session()
    session.headers.update(HEADERS)
    try:
        candidates, discovery = _search_http_candidates(query, session=session)
        product_pages = []
        for candidate in candidates[:25]:
            try:
                response = _request(session, candidate["url"])
                product_pages.append({"url": candidate["url"], "status": response.status_code, "final_url": response.url, "html_length": len(response.text or ""), "cloudflare": _is_challenge(response.text), "reader_fallback": False})
            except requests.RequestException as exc:
                try:
                    reader = _reader_request(session, candidate["url"])
                    product_pages.append({"url": candidate["url"], "status": getattr(getattr(exc, "response", None), "status_code", None), "error": f"{type(exc).__name__}: {exc}", "reader_status": reader.status_code, "reader_html_length": len(reader.text or ""), "reader_fallback": True})
                except requests.RequestException as reader_exc:
                    product_pages.append({"url": candidate["url"], "status": None, "error": f"{type(exc).__name__}: {exc}", "reader_error": f"{type(reader_exc).__name__}: {reader_exc}", "reader_fallback": True})
        return {"diagnostic": True, "scraper_version": SCRAPER_VERSION, "query": query, "search_url": _search_urls(query)[0], "discovery": discovery, "candidate_count": len(candidates), "candidates": candidates[:25], "product_pages": product_pages}
    finally:
        session.close()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()
    print(json.dumps(diagnose(args.query) if args.diagnose else search(args.query), ensure_ascii=False, indent=2))
