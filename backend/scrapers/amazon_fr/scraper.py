"""Public Amazon marketplace search adapter.

Reads ordinary public search result pages only. It does not use private APIs,
affiliate redirects, CAPTCHA bypass, or browser fingerprint evasion. If Amazon
blocks a request, the adapter reports that explicitly instead of inventing offers.
"""
from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from ..amazon_creators_api import is_configured as _creators_api_is_configured
from ..amazon_creators_api import search_marketplace as _creators_api_search

STORE = "Amazon"
MARKET = "fr"
BASE = "https://www.amazon.fr"
LANGUAGE = "fr-FR,fr;q=0.9,en;q=0.7"
TIMEOUT = (3.0, 6.0)
MAX_RESULTS = 20
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": LANGUAGE,
}


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _price(value):
    raw = _clean(value).replace("\u00a0", " ").replace("€", "").replace("EUR", "").strip()
    raw = re.sub(r"[^0-9,.]", "", raw)
    if not raw:
        return None
    if "," in raw and "." in raw:
        decimal = "," if raw.rfind(",") > raw.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        raw = raw.replace(thousands, "").replace(decimal, ".")
    elif "," in raw:
        tail = raw.rsplit(",", 1)[1]
        raw = raw.replace(",", ".") if len(tail) in (1, 2) else raw.replace(",", "")
    elif "." in raw and len(raw.rsplit(".", 1)[1]) not in (1, 2):
        raw = raw.replace(".", "")
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def _allowed_product_url(raw_url):
    absolute = urljoin(BASE, str(raw_url or ""))
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or parsed.hostname not in {urlparse(BASE).hostname, urlparse(BASE).hostname.replace("www.", "")}:
        return None
    match = re.fullmatch(r"/(?:dp|gp/product)/([A-Z0-9]{10})/?", parsed.path, re.I)
    if not match:
        return None
    return f"{BASE}/dp/{match.group(1).upper()}"


def _size_ml(text):
    match = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)[\s_-]*(ml|cl)\b", text, re.I)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10
    return int(value) if value.is_integer() else value


def _concentration(text):
    low = _clean(text).lower()
    for pattern, label in (
        (r"eau de toilette|\bedt\b", "Eau de Toilette"),
        (r"eau de parfum|\bedp\b", "Eau de Parfum"),
        (r"eau de cologne|\bedc\b", "Eau de Cologne"),
        (r"extrait(?: de parfum)?", "Extrait de Parfum"),
        (r"\bparfum\b", "Parfum"),
    ):
        if re.search(pattern, low):
            return label
    return None


def _looks_like_query(query, title):
    tokens = [x for x in re.findall(r"[a-z0-9]+", query.lower()) if len(x) > 1]
    haystack = set(re.findall(r"[a-z0-9]+", title.lower()))
    # Conservative admission: avoid returning unrelated results as matches.
    return bool(tokens) and all(token in haystack for token in tokens)


def _parse_public_search_html(query, html):
    lower = str(html or "")[:200000].lower()
    if any(marker in lower for marker in (
        "captcha", "robot check", "enter the characters you see",
        "sorry, we just need to make sure", "automated access",
    )):
        return {
            "status": "blocked", "verified": False, "results": [],
            "error": "amazon_challenge_page",
            "details": {"market": MARKET, "source": "public_search_html"},
        }
    soup = BeautifulSoup(html or "", "html.parser")
    rows = []
    seen = set()
    for card in soup.select('[data-component-type="s-search-result"][data-asin]'):
        asin = _clean(card.get("data-asin")).upper()
        if not re.fullmatch(r"[A-Z0-9]{10}", asin):
            continue
        title_node = card.select_one("h2 span")
        title = _clean(title_node.get_text(" ", strip=True) if title_node else "")
        if not title or not _looks_like_query(query, title):
            continue
        price_node = card.select_one(".a-price .a-offscreen")
        price = _price(price_node.get_text(" ", strip=True) if price_node else "")
        if price is None:
            continue
        product_url = _allowed_product_url(f"/dp/{asin}")
        if not product_url or product_url in seen:
            continue
        seen.add(product_url)
        image_node = card.select_one("img.s-image")
        image = _clean(image_node.get("src")) if image_node else None
        brand = next((token for token in query.split() if token.lower() in title.lower()), "")
        rows.append({
            "shop": f"Amazon.{'fr' if MARKET == 'fr' else 'de'}",
            "store": f"amazon_{MARKET}",
            "brand": brand,
            "name": title,
            "price": f"{price:.2f} €",
            "price_num": price,
            "currency": "EUR",
            "available": None,
            "availability": None,
            "image": image,
            "size_ml": _size_ml(title),
            "concentration": _concentration(title),
            "url": product_url,
        })
        if len(rows) >= MAX_RESULTS:
            break
    return {
        "status": "success", "verified": True, "results": rows, "error": None,
        "details": {"market": MARKET, "candidate_count": len(rows), "source": "public_search_html"},
    }


def _browser_public_search(query):
    """Retry an HTTP 503 through a normal headless Chromium page; never bypass challenges."""
    from playwright.sync_api import sync_playwright

    url = f"{BASE}/s?k={quote_plus(query)}"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        try:
            page = browser.new_page(locale=LANGUAGE.split(",")[0])
            response = page.goto(url, wait_until="domcontentloaded", timeout=5500)
            status = response.status if response else None
            html = page.content()
            if status in (403, 429):
                return {
                    "status": "blocked", "verified": False, "results": [],
                    "error": f"blocked_http_{status}",
                    "details": {"market": MARKET, "source": "public_browser"},
                }
            if status is not None and status >= 400:
                return {
                    "status": "unavailable", "verified": False, "results": [],
                    "error": f"amazon_http_{status}",
                    "details": {"market": MARKET, "source": "public_browser"},
                }
            report = _parse_public_search_html(query, html)
            report["details"]["source"] = "public_browser"
            return report
        finally:
            browser.close()


def _public_html_search(query):
    url = f"{BASE}/s?k={quote_plus(query)}"
    response = None
    try:
        response = requests.get(
            url, headers=HEADERS, timeout=(2.0, 3.0), allow_redirects=True
        )
        final = urlparse(response.url)
        if final.scheme != "https" or final.hostname not in {
            urlparse(BASE).hostname, urlparse(BASE).hostname.replace("www.", "")
        }:
            return {
                "status": "unavailable", "verified": False, "results": [],
                "error": "redirected_outside_market", "details": {"market": MARKET},
            }
        if response.status_code in (403, 429):
            return {
                "status": "blocked", "verified": False, "results": [],
                "error": f"blocked_http_{response.status_code}", "details": {"market": MARKET},
            }
        if response.status_code == 503:
            response.close()
            response = None
            try:
                return _browser_public_search(query)
            except Exception as exc:
                return {
                    "status": "unavailable", "verified": False, "results": [],
                    "error": f"amazon_browser_fallback:{type(exc).__name__}",
                    "details": {"market": MARKET, "source": "public_browser"},
                }
        response.raise_for_status()
        return _parse_public_search_html(query, response.text)
    except requests.Timeout:
        return {
            "status": "timeout", "verified": False, "results": [],
            "error": "amazon_request_timeout", "details": {"market": MARKET},
        }
    except requests.RequestException as exc:
        return {
            "status": "unavailable", "verified": False, "results": [],
            "error": f"amazon_request_error:{type(exc).__name__}",
            "details": {"market": MARKET},
        }
    finally:
        if response is not None:
            response.close()


def search(query):
    """Prefer approved Creators API; otherwise try ordinary public search HTML."""
    query = _clean(query)
    if not query:
        return {"status": "success", "verified": True, "results": [], "error": None,
                "details": {"empty_query": True}}
    if _creators_api_is_configured(MARKET):
        return _creators_api_search(query, MARKET, f"amazon_{MARKET}", _size_ml, _concentration)
    return _public_html_search(query)
