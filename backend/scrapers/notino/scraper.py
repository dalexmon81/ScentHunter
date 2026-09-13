from __future__ import annotations

import difflib
import html as html_lib
import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
SITEMAP_URL = BASE_URL + "/sitemap.xml"
READER_BASE = "https://r.jina.ai/"

TIMEOUT = 12
READER_TIMEOUT = 10
ENGINE_TIMEOUT = 10
SCRAPER_VERSION = "notino-generic-discovery-2026-09-13-v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

PRICE_RE = re.compile(
    r"(?:€\s*(\d{1,4}[.,]\d{2})|(\d{1,4}[.,]\d{2})\s*€)", re.I
)
SIZE_RE = re.compile(
    r"\b(\d{1,4}(?:[.,]\d{1,2})?)\s*(ml|cl|dl|l|oz|fl\s*oz|g|kg)\b",
    re.I,
)
RATING_RE = re.compile(r"\b\d[.,]\d\s*\(\s*\d+\s*\)", re.I)
PRODUCT_ID_RE = re.compile(r"/p-\d+(?:/|$)", re.I)

CHALLENGE_MARKERS = (
    "just a moment", "cf-chl-", "challenge-platform",
    "checking your browser", "verify you are human",
    "enable javascript and cookies", "vérification de sécurité en cours",
)

IN_STOCK_MARKERS = ("en stock", "ajouter au panier", "add to cart")
OUT_STOCK_MARKERS = (
    "en rupture de stock", "rupture de stock",
    "actuellement indisponible", "produit indisponible",
    "non disponible", "pas disponible", "épuisé",
)

NON_PERFUME_MARKERS = {
    "gift set", "set cadeau", "discovery set", "fragrance set",
    "perfume set", "parfum set", "coffret", "coffret cadeau",
    "bundle", "pack", "travel set", "kit", "duo", "trio",
    "mystery box", "tester", "testeur", "sample", "miniature",
    "échantillon", "shampoo", "shower gel", "gel douche",
    "body wash", "body lotion", "lotion corps", "body cream",
    "crème corps", "body milk", "deodorant", "déodorant",
    "deo spray", "aftershave", "after shave", "après-rasage",
    "body spray", "spray corps", "hair mist", "brume",
    "makeup", "cosmetics", "skincare", "skin care",
}

BLOCKED_PATHS = (
    "/search", "/avis/", "/erfahrungen/", "/magazine/", "/blog/",
    "/panier", "/cart", "/login", "/compte", "/account", "/contact",
    "/livraison", "/conditions", "/marques", "/parfums",
    "/cosmetiques", "/cheveux", "/dentaire",
)


def _clean(value: Any) -> str:
    text = html_lib.unescape(str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", _clean(value).lower())).strip()


def _tokens(value: Any) -> List[str]:
    return [x for x in re.findall(r"[a-z0-9]+", _clean(value).lower()) if len(x) > 1]


def _query_tokens(value: Any) -> List[str]:
    return _tokens(SIZE_RE.sub(" ", _clean(value)))


def _fuzzy_match(name: Any, query: Any) -> Tuple[bool, Dict[str, bool], int]:
    nt = set(_query_tokens(name))
    qt = _query_tokens(query)
    if not nt or not qt:
        return False, {}, 0
    hits: Dict[str, bool] = {}
    fuzzy = 0
    for token in qt:
        if token in nt:
            hits[token] = True
            continue
        ratio = max(
            (difflib.SequenceMatcher(None, token, candidate).ratio() for candidate in nt),
            default=0.0,
        )
        lengths = [
            abs(len(token) - len(candidate))
            for candidate in nt
            if difflib.SequenceMatcher(None, token, candidate).ratio() >= 0.82
        ]
        hit = ratio >= 0.82 and bool(lengths) and min(lengths) <= 2
        hits[token] = hit
        fuzzy += int(hit)
    return all(hits.values()), hits, fuzzy


def _requested_sizes(value: Any) -> List[Tuple[str, str]]:
    out = []
    for m in SIZE_RE.finditer(_clean(value)):
        out.append((m.group(1).replace(",", "."), re.sub(r"\s+", "", m.group(2).lower())))
    return out


def _size_matches(text: Any, size: Tuple[str, str]) -> bool:
    number, unit = size
    number_re = re.escape(number).replace(r"\.", r"[.,]")
    unit_re = r"fl\s*oz" if unit == "floz" else re.escape(unit)
    return bool(re.search(rf"\b{number_re}\s*{unit_re}\b", _clean(text), re.I))


def _size_valid(text: str, query: str) -> bool:
    requested = _requested_sizes(query)
    if not requested:
        return True
    if not SIZE_RE.search(_clean(text)):
        return True
    return any(_size_matches(text, x) for x in requested)


def _format_price(value: Any) -> str:
    m = re.search(r"(\d{1,4}(?:[.,]\d{1,2})?)", _clean(value))
    if not m:
        return ""
    try:
        n = float(m.group(1).replace(",", "."))
    except ValueError:
        return ""
    return f"{n:.2f}".replace(".", ",") + "€" if n > 0 else ""


def _extract_price(text: Any) -> str:
    text = _clean(text)
    matches = list(PRICE_RE.finditer(text))
    for m in reversed(matches):
        after = text[m.end():m.end() + 25]
        if re.match(r"\s*/\s*100\s*(?:ml|g)", after, re.I):
            continue
        return _format_price(m.group(1) or m.group(2))
    return ""


def _extract_product_price(text: Any) -> str:
    text = _clean(text)
    if not text:
        return ""

    for m in reversed(list(re.finditer(
        r"prix\s+actuel\s+(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
        text, re.I
    ))):
        if not re.match(r"\s*/\s*100\s*(?:ml|g)", text[m.end():m.end() + 25], re.I):
            return _format_price(m.group(1))

    sized = re.findall(
        r"\b\d{1,4}(?:[.,]\d{1,2})?\s*(?:ml|cl|dl|l|oz|fl\s*oz|g|kg)\s+"
        r"(?:de\s+)?(\d{1,4}[.,]\d{2})\s*€",
        text, re.I
    )
    if sized:
        return _format_price(sized[-1])

    return _extract_price(text)


def _is_challenge(text: str) -> bool:
    low = _clean(text).lower()
    return any(x in low for x in CHALLENGE_MARKERS)


def _is_non_perfume(value: Any) -> bool:
    tokens = set(_norm(value).split())
    return any(set(_norm(x).split()).issubset(tokens) for x in NON_PERFUME_MARKERS)


def _non_perfume_product(name: Any, url: Any = "", title: Any = "") -> bool:
    if _is_non_perfume(name) or _is_non_perfume(title):
        return True
    try:
        path = unquote(urlparse(str(url or "")).path)
    except Exception:
        path = str(url or "")
    return _is_non_perfume(path)


def _looks_like_product_url(url: str) -> bool:
    try:
        p = urlparse(url)
    except Exception:
        return False
    if p.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return False
    path = p.path.rstrip("/")
    if not path or any(path.lower() == x.rstrip("/") or path.lower().startswith(x) for x in BLOCKED_PATHS):
        return False
    parts = [x for x in path.split("/") if x]
    return len(parts) >= 2 and (bool(PRODUCT_ID_RE.search(path)) or len(parts) == 2)


def _normalise_url(raw: Any) -> Optional[str]:
    value = html_lib.unescape(str(raw or "")).strip()
    value = value.replace("\\/", "/").replace("\\u002F", "/")
    value = unquote(value).strip(" <>\"'()[]{}.,;")
    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(BASE_URL, value)
    try:
        p = urlparse(value)
    except Exception:
        return None
    if p.netloc.lower() not in {"www.notino.fr", "notino.fr"}:
        return None
    result = f"https://{p.netloc.lower()}{p.path.rstrip('/')}"
    return result if _looks_like_product_url(result) else None


def _url_name(url: str) -> str:
    try:
        parts = [x for x in unquote(urlparse(url).path).strip("/").split("/") if x]
    except Exception:
        return ""
    if len(parts) < 2:
        return ""
    slug = parts[-2] if parts[-1].lower().startswith("p-") else parts[-1]
    slug = re.sub(r"-\d{5,}$", "", slug)
    return _clean(re.sub(r"[-_]+", " ", slug))


def _url_brand(url: str) -> str:
    try:
        parts = [x for x in unquote(urlparse(url).path).strip("/").split("/") if x]
    except Exception:
        return ""
    return _clean(parts[0].replace("-", " ")) if len(parts) >= 2 else ""


def _clean_name(text: Any) -> str:
    value = _clean(text)
    value = RATING_RE.sub(" ", value)
    value = PRICE_RE.sub(" ", value)
    value = re.sub(
        r"^(?:promo|promotion|nouveau|discount|cadeaux?\s+offerts?|livraison\s+offerte)\s+",
        "", value, flags=re.I
    )
    words = value.split()
    if len(words) >= 4 and len(words) % 2 == 0:
        half = len(words) // 2
        if words[:half] == words[half:]:
            value = " ".join(words[:half])
    return _clean(value)


def _display_name(name: Any, url: str, brand_hint: str = "") -> str:
    raw = _clean_name(name)
    brand = _clean_name(brand_hint) or _url_brand(url)
    if not raw or not brand:
        return raw
    prefix = re.compile(r"^" + re.escape(brand) + r"(?:\s*[-–—:]\s*|\s+)", re.I)
    variant = prefix.sub("", raw, count=1).strip()
    return brand if not variant else f"{brand} - {variant}"


def _make_candidate(url: str, name: str, context: str, query: str, source: str, price: str = "") -> Optional[Dict[str, Any]]:
    url = _normalise_url(url) or ""
    if not url:
        return None
    name = _clean_name(name)
    if not name or _non_perfume_product(name, url):
        return None

    url_name = _url_name(url)
    combined = f"{name} {url_name} {context}"
    matched, hits, fuzzy = _fuzzy_match(combined, query)
    if not matched:
        return None

    score = sum(hits.values()) * 5 + fuzzy * 2
    if _fuzzy_match(url_name, query)[0]:
        score += 20
    if price:
        score += 2
    if _requested_sizes(query) and any(_size_matches(context, s) for s in _requested_sizes(query)):
        score += 6

    return {
        "url": url,
        "name": name,
        "anchor_text": name,
        "card_text": _clean(context),
        "price_hint": price,
        "score": score,
        "source": source,
    }


def _bing_url(href: str) -> Optional[str]:
    href = html_lib.unescape(_clean(href))
    direct = re.search(
        r"https?://(?:www\.)?notino\.fr/[^\s&<>\"']+",
        href, re.I
    )
    if direct:
        return _normalise_url(direct.group(0))
    m = re.search(r"[?&](?:q|url)=([^&]+)", href, re.I)
    if m:
        return _normalise_url(unquote(m.group(1)))
    return None


def _bing(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    q = f'site:notino.fr "{query}"'
    url = "https://www.bing.com/search?q=" + quote_plus(q)
    report = {"engine": "bing", "url": url, "status": None, "candidate_count": 0, "error": None}

    try:
        r = session.get(url, timeout=ENGINE_TIMEOUT, headers=HEADERS)
        report["status"] = r.status_code
        r.raise_for_status()
    except requests.RequestException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return [], report

    soup = BeautifulSoup(r.text or "", "html.parser")
    blocks = soup.select("li.b_algo, div.b_algo")
    found: Dict[str, Dict[str, Any]] = {}

    for block in blocks:
        a = block.select_one("h2 a, h3 a") or block.find("a", href=True)
        if not a:
            continue
        href = _bing_url(a.get("href", ""))
        if not href:
            continue

        title = _clean_name(a.get_text(" ", strip=True))
        context = _clean(block.get_text(" ", strip=True))
        price = _extract_product_price(context) or _extract_price(title)
        name = title if _fuzzy_match(title, query)[0] else _url_name(href)

        brand = _url_brand(href)
        if brand and _url_name(href):
            branded = _clean(f"{brand} {_url_name(href)}")
            if _fuzzy_match(branded, query)[0]:
                name = branded

        candidate = _make_candidate(href, name, context, query, "bing", price)
        if candidate and price:
            old = found.get(candidate["url"])
            if old is None or candidate["score"] > old["score"]:
                found[candidate["url"]] = candidate

    result = sorted(found.values(), key=lambda x: (-x["score"], x["url"]))
    report["candidate_count"] = len(result)
    return result, report


def _bing_rss(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    q = f'site:notino.fr "{query}"'
    url = "https://www.bing.com/search?format=rss&q=" + quote_plus(q)
    report = {"engine": "bing-rss", "url": url, "status": None, "candidate_count": 0, "error": None}

    try:
        r = session.get(url, timeout=ENGINE_TIMEOUT, headers=HEADERS)
        report["status"] = r.status_code
        r.raise_for_status()
    except requests.RequestException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return [], report

    found = {}

    # ElementTree is built into Python, so this does not require
    # BeautifulSoup's optional XML tree-builder on Render.
    try:
        root = ET.fromstring(r.text or "")
        items = root.findall(".//item")
    except ET.ParseError:
        items = []

    for item in items:
        title_node = item.find("title")
        desc_node = item.find("description")
        link_node = item.find("link")
        title = _clean(title_node.text or "") if title_node is not None else ""
        desc = _clean(desc_node.text or "") if desc_node is not None else ""
        link = _clean(link_node.text or "") if link_node is not None else ""
        href = _normalise_url(link)
        if not href:
            m = re.search(r"https?://(?:www\.)?notino\.fr/[^\s<>\"]+", desc, re.I)
            href = _normalise_url(m.group(0)) if m else None
        if not href:
            continue
        price = _extract_product_price(desc) or _extract_price(title)
        name = _clean_name(title) or _url_name(href)
        if price and _fuzzy_match(f"{name} {desc} {_url_name(href)}", query)[0]:
            candidate = _make_candidate(href, name, desc, query, "bing-rss", price)
            if candidate:
                found[href] = candidate

    result = sorted(found.values(), key=lambda x: (-x["score"], x["url"]))
    report["candidate_count"] = len(result)
    return result, report


def _google(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    q = f'site:notino.fr "{query}"'
    url = "https://www.google.com/search?q=" + quote_plus(q)
    report = {"engine": "google", "url": url, "status": None, "candidate_count": 0, "error": None}

    try:
        r = session.get(url, timeout=ENGINE_TIMEOUT, headers=HEADERS)
        report["status"] = r.status_code
        r.raise_for_status()
    except requests.RequestException as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return [], report

    soup = BeautifulSoup(r.text or "", "html.parser")
    found = {}

    for a in soup.find_all("a", href=True):
        href_raw = _clean(a.get("href", ""))
        href = _normalise_url(href_raw)
        if not href:
            m = re.search(r"[?&](?:q|url)=([^&]+)", href_raw, re.I)
            href = _normalise_url(unquote(m.group(1))) if m else None
        if not href:
            continue

        title = _clean_name(a.get_text(" ", strip=True))
        parent = a
        context = title
        for _ in range(5):
            parent = parent.parent
            if parent is None:
                break
            text = _clean(parent.get_text(" ", strip=True))
            if len(text) > len(context):
                context = text
            if len(text) >= 120:
                break

        price = _extract_product_price(context) or _extract_price(title)
        name = title if _fuzzy_match(title, query)[0] else _url_name(href)
        if price:
            candidate = _make_candidate(href, name, context, query, "google", price)
            if candidate:
                found[href] = candidate

    result = sorted(found.values(), key=lambda x: (-x["score"], x["url"]))
    report["candidate_count"] = len(result)
    return result, report


def _direct_search(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    reports = []
    found = {}

    for url in (
        SEARCH_URL + "?exps=" + quote_plus(query),
        BASE_URL + "/search?query=" + quote_plus(query),
        BASE_URL + "/search?exps=" + quote_plus(query),
    ):
        try:
            r = session.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
            reports.append({
                "url": url, "final_url": r.url, "status": r.status_code,
                "html_length": len(r.text or ""), "challenge": _is_challenge(r.text or "")
            })
            if r.status_code != 200 or _is_challenge(r.text or ""):
                continue

            soup = BeautifulSoup(r.text or "", "html.parser")
            for a in soup.find_all("a", href=True):
                href = _normalise_url(urljoin(BASE_URL, a.get("href", "")))
                if not href:
                    continue
                parent = a
                context = _clean(a.get_text(" ", strip=True))
                for _ in range(10):
                    parent = parent.parent
                    if parent is None:
                        break
                    text = _clean(parent.get_text(" ", strip=True))
                    if len(text) > len(context):
                        context = text
                    if _extract_price(text):
                        break
                name = _clean_name(a.get("title") or a.get("aria-label") or a.get_text(" ", strip=True))
                if not name:
                    name = _url_name(href)
                price = _extract_product_price(context)
                candidate = _make_candidate(href, name, context, query, "direct", price)
                if candidate and price:
                    found[href] = candidate
            if found:
                break
        except requests.RequestException as exc:
            reports.append({"url": url, "error": f"{type(exc).__name__}: {exc}"})

    return sorted(found.values(), key=lambda x: (-x["score"], x["url"])), {
        "engine": "notino-direct",
        "pages": reports,
        "candidate_count": len(found),
    }


def _reader_candidates(text: str, query: str) -> List[Dict[str, Any]]:
    raw = html_lib.unescape(text or "").replace("\\/", "/")
    found = {}
    for match in re.finditer(
        r"https?://(?:www\.)?notino\.fr/[^\s<>)\]\"']+",
        raw, re.I
    ):
        href = _normalise_url(match.group(0))
        if not href:
            continue
        name = _url_name(href)
        brand = _url_brand(href)
        branded = _clean(f"{brand} {name}") if brand else name
        if _fuzzy_match(branded, query)[0]:
            name = branded
        context = raw[max(0, match.start()-500):match.end()+500]
        price = _extract_product_price(context) or _extract_price(context)
        candidate = _make_candidate(href, name, context, query, "reader", price)
        if candidate and price:
            found[href] = candidate
    return sorted(found.values(), key=lambda x: (-x["score"], x["url"]))


def _reader_search(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    reports = []
    found = {}
    variants = []
    for value in (query, " ".join(reversed(_query_tokens(query))), *_query_tokens(query)):
        value = _clean(value)
        if value and value not in variants:
            variants.append(value)

    for variant in variants:
        for search_url in (
            SEARCH_URL + "?exps=" + quote_plus(variant),
            BASE_URL + "/search?query=" + quote_plus(variant),
        ):
            try:
                target = READER_BASE + search_url
                r = session.get(target, timeout=READER_TIMEOUT, headers=HEADERS)
                reports.append({
                    "url": search_url, "status": r.status_code,
                    "html_length": len(r.text or "")
                })
                if r.status_code != 200:
                    continue
                for candidate in _reader_candidates(r.text, query):
                    old = found.get(candidate["url"])
                    if old is None or candidate["score"] > old["score"]:
                        found[candidate["url"]] = candidate
            except requests.RequestException as exc:
                reports.append({"url": search_url, "error": f"{type(exc).__name__}: {exc}"})

    return sorted(found.values(), key=lambda x: (-x["score"], x["url"])), {
        "engine": "jina-reader",
        "pages": reports,
        "candidate_count": len(found),
    }


def _fetch_product(session: requests.Session, candidate: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
    url = candidate["url"]

    try:
        r = session.get(url, timeout=TIMEOUT, headers=HEADERS, allow_redirects=True)
        if r.status_code == 200 and not _is_challenge(r.text or ""):
            final_url = _normalise_url(r.url) or url
            soup = BeautifulSoup(r.text or "", "html.parser")
            page_text = _clean(soup.get_text(" ", strip=True))

            if not _size_valid(page_text, query):
                return None

            name = ""
            brand = ""

            for product in _json_ld_products(soup):
                pname = _clean(product.get("name"))
                pbrand = product.get("brand")
                pbrand = _clean(pbrand.get("name")) if isinstance(pbrand, dict) else _clean(pbrand)
                if pname and _fuzzy_match(f"{pbrand} {pname}", query)[0]:
                    name = pname
                    brand = pbrand
                    break

            if not name:
                h1 = soup.find("h1")
                if h1:
                    h = _clean(h1.get_text(" ", strip=True))
                    if _fuzzy_match(h, query)[0]:
                        name = h

            if not name:
                name = candidate.get("name", "")

            price = ""
            for product in _json_ld_products(soup):
                pname = _clean(product.get("name"))
                if pname and name and _fuzzy_match(pname, name)[0]:
                    price, _ = _offer_data(product.get("offers"))
                    if price:
                        break

            price = price or _extract_product_price(page_text) or candidate.get("price_hint", "")

            if name and price and not _non_perfume_product(name, final_url, page_text):
                low = page_text.lower()
                if not (any(x in low for x in OUT_STOCK_MARKERS) and not any(x in low for x in IN_STOCK_MARKERS)):
                    return {
                        "store": STORE,
                        "name": _display_name(name, final_url, brand),
                        "price": price,
                        "url": final_url,
                    }
    except requests.RequestException:
        pass

    # Critical fallback: if Notino itself returns 403, preserve the
    # independently discovered search-engine price instead of losing the hit.
    name = candidate.get("name", "")
    price = candidate.get("price_hint", "")
    if name and price and not _non_perfume_product(name, url):
        return {
            "store": STORE,
            "name": _display_name(name, url),
            "price": price,
            "url": url,
        }

    return None


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



def _browser_search(query: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Discover Notino products through a real Chromium page.

    Render's normal HTTP client is challenged by Cloudflare, while the
    Playwright Chromium session can load the search page and expose the
    product cards in the rendered DOM.  Product pages themselves are not
    fetched here; the search-card data is sufficient for ScentHunter.
    """
    report: Dict[str, Any] = {
        "engine": "playwright-notino",
        "status": None,
        "candidate_count": 0,
        "error": None,
        "elapsed_s": 0.0,
    }
    found: Dict[str, Dict[str, Any]] = {}
    started = __import__("time").perf_counter()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        report["error"] = f"Playwright unavailable: {type(exc).__name__}: {exc}"
        return [], report

    url = SEARCH_URL + "?exps=" + quote_plus(query)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="fr-FR",
                viewport={"width": 1365, "height": 900},
            )
            page = context.new_page()
            response = page.goto(url, wait_until="domcontentloaded", timeout=25000)
            report["status"] = response.status if response else None

            # The diagnostic proved that the rendered page is already useful
            # without waiting for networkidle (which can waste 10+ seconds on
            # tracking/Cloudflare requests).
            page.wait_for_timeout(1800)

            if _is_challenge(_clean(BeautifulSoup(page.content(), "html.parser").get_text(" ", strip=True))):
                # Give the Cloudflare JS challenge a short additional window.
                page.wait_for_timeout(2500)

            # Work from product anchors and climb to the smallest useful card.
            # This deliberately avoids depending on a fragile CSS class/name.
            anchors = page.locator("a[href*='/p-']")
            count = min(anchors.count(), 1500)

            for i in range(count):
                a = anchors.nth(i)
                try:
                    href_raw = a.get_attribute("href") or ""
                    href = _normalise_url(urljoin(BASE_URL, href_raw))
                    if not href:
                        continue

                    anchor_text = _clean(a.inner_text(timeout=1500))
                    if not anchor_text:
                        anchor_text = _clean(a.get_attribute("title") or "")

                    # Collect text from progressively larger ancestors.  We
                    # stop at the first one that contains a price, which tends
                    # to be the product tile rather than the whole page.
                    context = anchor_text
                    node = a
                    for _ in range(8):
                        try:
                            node = node.locator("..")
                            text = _clean(node.inner_text(timeout=1000))
                        except Exception:
                            break
                        if len(text) > len(context):
                            context = text
                        if _extract_price(text):
                            break
                        if len(text) > 1800:
                            break

                    # Some Notino cards expose the title on a descendant while
                    # the first product anchor itself is an image/link.  Use
                    # the URL slug as a stable fallback name.
                    name = _clean_name(anchor_text) or _url_name(href)
                    if not _fuzzy_match(f"{name} {context} {_url_name(href)}", query)[0]:
                        # Retry using the complete card text; this catches
                        # cases where the visible title is split across nodes.
                        name_match = _fuzzy_match(context, query)[0]
                        if not name_match:
                            continue
                        name = _url_name(href)

                    if _non_perfume_product(name, href, context):
                        continue
                    if not _size_valid(context, query):
                        continue

                    price = _extract_product_price(context) or _extract_price(context)
                    if not price:
                        continue

                    candidate = _make_candidate(
                        href, name, context, query, "playwright", price
                    )
                    if candidate:
                        # Prefer the richest/most exact card when the same
                        # product has multiple anchors (image + title + CTA).
                        old = found.get(candidate["url"])
                        if old is None or candidate["score"] > old["score"]:
                            found[candidate["url"]] = candidate
                except Exception:
                    continue

            context.close()
            browser.close()

    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    result = sorted(found.values(), key=lambda x: (-x["score"], x["url"]))
    report["candidate_count"] = len(result)
    report["elapsed_s"] = round(__import__("time").perf_counter() - started, 3)
    return result, report

def _discover(query: str, session: requests.Session) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    all_found: Dict[str, Dict[str, Any]] = {}
    reports = []

    # Chromium is the primary Notino path on Render.  The live diagnostic
    # proved that it receives HTTP 200 and exposes the actual product URLs,
    # whereas requests/Jina receive Cloudflare 403.  If Chromium succeeds,
    # return immediately: there is no reason to spend 30-50 seconds querying
    # channels that are known to be blocked or incomplete.
    browser_candidates, browser_report = _browser_search(query)
    reports.append(browser_report)
    for candidate in browser_candidates:
        all_found[candidate["url"]] = candidate

    if browser_candidates:
        ordered = sorted(all_found.values(), key=lambda x: (-x["score"], x["url"]))
        return ordered[:12], {
            "query": query,
            "channels": reports,
            "candidate_count": len(ordered),
            "candidates": ordered[:12],
            "primary_channel": "playwright-notino",
        }

    # Fallbacks remain intact if Chromium is unavailable or cannot solve the
    # challenge on a future Notino/Render change.
    channels = (
        _direct_search(query, session),
        _bing(query, session),
        _bing_rss(query, session),
        _google(query, session),
        _reader_search(query, session),
    )

    for candidates, report in channels:
        reports.append(report)
        for candidate in candidates:
            old = all_found.get(candidate["url"])
            if old is None or candidate["score"] > old["score"]:
                all_found[candidate["url"]] = candidate

    ordered = sorted(all_found.values(), key=lambda x: (-x["score"], x["url"]))
    return ordered[:12], {
        "query": query,
        "channels": reports,
        "candidate_count": len(ordered),
        "candidates": ordered[:12],
    }


def search(query: str) -> List[Dict[str, Any]]:
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        candidates, _ = _discover(query, session)
        results = []
        seen = set()

        for candidate in candidates:
            result = _fetch_product(session, candidate, query)
            if not result:
                continue

            key = (
                result.get("url", "").lower()
                + "|"
                + _norm(result.get("name", ""))
            )

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


def search_stream(query: str):
    # Kept compatible with ScentHunter's progressive worker contract.
    for result in search(query):
        yield result


def diagnose(query: str) -> Dict[str, Any]:
    """Full diagnostic for the Notino failure on Render.

    This never calls search() and never hides failures behind count=0.
    It reports each discovery channel, candidate URLs, direct product
    access, and a root-cause classification.
    """
    import os
    import socket
    import time
    import traceback

    query = _clean(query)
    started = time.perf_counter()
    if not query:
        return {"diagnostic": True, "error": "empty_query"}

    session = requests.Session()
    session.headers.update(HEADERS)

    def probe(url: str, label: str, timeout: float = 15.0) -> Dict[str, Any]:
        t0 = time.perf_counter()
        try:
            r = session.get(url, timeout=timeout, headers=HEADERS, allow_redirects=True)
            body = r.text or ""
            soup = BeautifulSoup(body, "html.parser")
            text = _clean(soup.get_text(" ", strip=True))
            links = set()
            for a in soup.find_all("a", href=True):
                u = _normalise_url(urljoin(BASE_URL, a.get("href", "")))
                if u:
                    links.add(u)
            products = sorted(u for u in links if PRODUCT_ID_RE.search(u))
            # Also catch raw URLs embedded in search-engine HTML/JSON.
            for m in re.finditer(r"https?://(?:www\.)?notino\.fr/[^\s<>\"']+", body, re.I):
                u = _normalise_url(m.group(0))
                if u and PRODUCT_ID_RE.search(u):
                    products.append(u)
            products = sorted(set(products))
            return {
                "label": label,
                "url": url,
                "final_url": r.url,
                "status": r.status_code,
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "content_type": r.headers.get("content-type", ""),
                "server": r.headers.get("server", ""),
                "html_length": len(body),
                "title": _clean(soup.title.get_text(" ", strip=True) if soup.title else ""),
                "h1": _clean(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""),
                "challenge": _is_challenge(body),
                "product_link_count": len(products),
                "product_links": products[:30],
                "anchor_count": len(links),
                "body_preview": text[:1500],
            }
        except Exception as exc:
            return {
                "label": label, "url": url, "status": None,
                "elapsed_s": round(time.perf_counter() - t0, 3),
                "error_type": type(exc).__name__, "error": str(exc),
            }

    try:
        encoded = quote_plus(query)
        direct_urls = (
            SEARCH_URL + "?exps=" + encoded,
            BASE_URL + "/search?query=" + encoded,
            BASE_URL + "/search?exps=" + encoded,
        )
        direct = [probe(u, f"notino-direct-{i+1}") for i, u in enumerate(direct_urls)]

        engines = {
            "bing": probe("https://www.bing.com/search?q=" + quote_plus(f'site:notino.fr "{query}"'), "bing"),
            "google": probe("https://www.google.com/search?q=" + quote_plus(f'site:notino.fr "{query}"'), "google"),
            "jina": probe(READER_BASE + direct_urls[0], "jina"),
        }

        dns = {}
        try:
            addresses = sorted({x[4][0] for x in socket.getaddrinfo("www.notino.fr", 443, type=socket.SOCK_STREAM)})
            dns = {"ok": True, "addresses": addresses[:20]}
        except Exception as exc:
            dns = {"ok": False, "error_type": type(exc).__name__, "error": str(exc)}

        browser = {"available": False, "ok": False, "product_links": [], "product_link_count": 0}
        try:
            from playwright.sync_api import sync_playwright
            browser["available"] = True
            t0 = time.perf_counter()
            events = []
            with sync_playwright() as pw:
                b = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
                c = b.new_context(user_agent=HEADERS["User-Agent"], locale="fr-FR", viewport={"width": 1365, "height": 900})
                p = c.new_page()
                def on_response(resp):
                    try:
                        if urlparse(resp.url).netloc.lower() in {"www.notino.fr", "notino.fr"} and len(events) < 100:
                            events.append({"status": resp.status, "url": resp.url[:500], "type": resp.request.resource_type})
                    except Exception:
                        pass
                p.on("response", on_response)
                nav_error = None
                status = None
                try:
                    resp = p.goto(direct_urls[0], wait_until="domcontentloaded", timeout=30000)
                    status = resp.status if resp else None
                except Exception as exc:
                    nav_error = f"{type(exc).__name__}: {exc}"
                try:
                    p.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                p.wait_for_timeout(3000)
                body = p.content()
                soup = BeautifulSoup(body, "html.parser")
                text = _clean(soup.get_text(" ", strip=True))
                products = set()
                for a in soup.find_all("a", href=True):
                    u = _normalise_url(urljoin(BASE_URL, a.get("href", "")))
                    if u and PRODUCT_ID_RE.search(u):
                        products.add(u)
                browser.update({"ok": bool(status == 200 and products and not _is_challenge(text)), "initial_status": status,
                                "navigation_error": nav_error, "final_url": p.url, "html_length": len(body),
                                "title": _clean(soup.title.get_text(" ", strip=True) if soup.title else ""),
                                "h1": _clean(soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""),
                                "challenge": _is_challenge(text), "product_link_count": len(products),
                                "product_links": sorted(products)[:30], "body_preview": text[:1500], "network_events": events,
                                "elapsed_s": round(time.perf_counter()-t0, 3)})
                b.close()
        except Exception as exc:
            browser.update({"error_type": type(exc).__name__, "error": str(exc), "traceback": traceback.format_exc()})

        candidates = set()
        for item in direct + list(engines.values()):
            candidates.update(item.get("product_links", []))
        candidates.update(browser.get("product_links", []))

        product_pages = [probe(u, "notino-product") for u in sorted(candidates)[:12]]
        direct_403 = sum(x.get("status") == 403 for x in direct)
        direct_products = sum(x.get("product_link_count", 0) for x in direct)
        engine_products = sum(x.get("product_link_count", 0) for x in engines.values())
        browser_products = browser.get("product_link_count", 0)
        product_403 = sum(x.get("status") == 403 for x in product_pages)
        product_200 = sum(x.get("status") == 200 for x in product_pages)

        if browser_products > 0 and not browser.get("challenge"):
            code = "BROWSER_REACHES_NOTINO"
            cause = "Chromium on Render reaches Notino and exposes product URLs; the remaining bug is scraper parsing/filtering."
        elif direct_403 == len(direct) and browser.get("initial_status") == 403:
            code = "NOTINO_BLOCKS_RENDER_HTTP_AND_BROWSER"
            cause = "All direct Notino searches return 403 and Chromium also receives 403 without product URLs."
        elif direct_403 and engine_products == 0 and browser_products == 0:
            code = "NOTINO_HTTP_BLOCKED_NO_DISCOVERY"
            cause = "Notino blocks direct Render access and no external discovery channel returns a product URL."
        elif engine_products > 0 and product_403 > 0 and product_200 == 0:
            code = "DISCOVERY_WORKS_PRODUCT_ACCESS_BLOCKED"
            cause = "Product URLs are discovered, but Notino blocks product-page requests from Render."
        elif direct_products > 0:
            code = "DIRECT_SEARCH_WORKS"
            cause = "Notino search itself exposes product URLs; the failure is in candidate extraction/filtering."
        elif any(x.get("challenge") for x in direct):
            code = "NOTINO_CHALLENGE_PAGE"
            cause = "Notino returned a security/challenge page instead of normal search content."
        else:
            code = "UNDETERMINED"
            cause = "All probes completed but the evidence does not isolate one root cause."

        return {
            "diagnostic": True,
            "diagnostic_version": "notino-root-cause-2026-09-13-v4",
            "query": query,
            "elapsed_s": round(time.perf_counter()-started, 3),
            "dns": dns,
            "direct_notino": direct,
            "external_discovery": engines,
            "browser": browser,
            "candidate_urls": sorted(candidates)[:30],
            "candidate_count": len(candidates),
            "product_pages": product_pages,
            "conclusion": {
                "code": code,
                "cause": cause,
                "evidence": {
                    "direct_403_pages": direct_403,
                    "direct_product_links": direct_products,
                    "engine_product_links": engine_products,
                    "browser_product_links": browser_products,
                    "product_403_pages": product_403,
                    "product_200_pages": product_200,
                },
            },
        }
    except Exception as exc:
        return {
            "diagnostic": True,
            "diagnostic_version": "notino-root-cause-2026-09-13-v4",
            "query": query,
            "diagnostic_internal_error": True,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
    finally:
        session.close()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--diagnose", action="store_true")
    args = parser.parse_args()

    print(json.dumps(
        diagnose(args.query) if args.diagnose else search(args.query),
        ensure_ascii=False,
        indent=2,
    ))
