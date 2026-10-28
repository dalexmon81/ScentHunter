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
MARKET = "de"
BASE = "https://www.amazon.de"
LANGUAGE = "de-DE,de;q=0.9,en;q=0.7"
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


def search(query):
    """Search only through the explicitly approved Amazon Creators API.

    Public HTML search may be unavailable to this price-comparison service until
    Amazon has approved the relevant use. Do not silently substitute HTML offers.
    """
    query = _clean(query)
    if not query:
        return {"status": "success", "verified": True, "results": [], "error": None,
                "details": {"empty_query": True}}
    if not _creators_api_is_configured(MARKET):
        return {
            "status": "unavailable",
            "verified": False,
            "results": [],
            "error": "amazon_creators_api_not_configured_or_not_approved",
            "details": {"market": MARKET, "source": "amazon_creators_api"},
        }
    return _creators_api_search(query, MARKET, f"amazon_{MARKET}", _size_ml, _concentration)
