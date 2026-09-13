"""ScentHunter - Deloox fast scraper.

First-party Deloox discovery is used directly. Search/category pages already
contain product cards with names, sizes and prices, so product pages are only
used as a fallback when a card is incomplete. This avoids the old pattern of
fetching up to 12 product pages (with retries) serially in batches.
"""
from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE = "https://www.deloox.com"
TIMEOUT = (2.0, 5.0)
MAX_CANDIDATES = 8
MAX_RESULTS = 40

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)

NON_FRAGRANCE = (
    "body mist",
    "body spray",
    "body lotion",
    "body cream",
    "deodorant",
    "after shave",
    "aftershave",
    "shower gel",
    "soap",
    "hair mist",
)

PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,4}[.,]\d{2})(?:\s*€)?")


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(
        r"[^a-z0-9]+",
        " ",
        clean(v).lower(),
    ).strip()


def tokens(v):
    return {
        x
        for x in norm(v).split()
        if len(x) > 1
    }


def size_ml(*values):
    m = SIZE_RE.search(
        " ".join(
            clean(x)
            for x in values
            if x
        )
    )

    if not m:
        return None

    n = float(
        m.group(1).replace(",", ".")
    )

    if m.group(2).lower() == "cl":
        n *= 10

    return int(n) if n.is_integer() else n


def price_num(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return round(float(v), 2)

    text = clean(v).replace("\xa0", " ")
    matches = PRICE_RE.findall(text)

    for raw in matches:
        try:
            n = float(
                raw.replace(",", ".")
            )
        except ValueError:
            continue

        if 0 < n < 10000:
            return round(n, 2)

    return None


def price_text(v):
    n = price_num(v)

    return (
        f"{n:.2f}".replace(".", ",") + " €"
        if n is not None
        else None
    )


def availability(value):
    text = norm(value)

    if any(
        x in text
        for x in (
            "out of stock",
            "outofstock",
            "sold out",
            "soldout",
            "unavailable",
            "not available",
        )
    ):
        return "out_of_stock"

    if any(
        x in text
        for x in (
            "in stock",
            "instock",
            "available",
            "add to cart",
            "in winkelwagen",
        )
    ):
        return "in_stock"

    return None


def get(session, url):
    # One quick retry is enough. The old three-attempt/8.5s request budget was
    # the main reason Deloox could consume the whole 75s store timeout.
    for attempt in range(2):
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )

            if r.status_code == 200 and r.text:
                return r

            if r.status_code not in (
                429,
                500,
                502,
                503,
                504,
            ):
                return None

        except requests.RequestException:
            pass

        if attempt == 0:
            time.sleep(0.35)

    return None


def is_product_url(url):
    try:
        p = urlparse(url)
    except Exception:
        return False

    host = p.netloc.lower().split(":", 1)[0]

    if not re.fullmatch(
        r"(?:www\.)?deloox\.(?:com|nl|es|fr|de|it|be)",
        host,
    ):
        return False

    return bool(
        re.search(
            r"/(?:product|produit|producto)/\d+/",
            p.path,
            re.I,
        )
    )


def product_url(raw):
    url = (
        urljoin(
            BASE + "/",
            clean(raw),
        )
        .split("#", 1)[0]
        .split("?", 1)[0]
    )

    return (
        url
        if is_product_url(url)
        else ""
    )


def relevant(text, query):
    q = tokens(query)
    hay = norm(text)

    if not q:
        return False

    hits = sum(
        t in hay
        for t in q
    )

    return hits >= (
        1
        if len(q) == 1
        else max(2, len(q) - 1)
    )


def non_fragrance(text):
    t = norm(text)

    return any(
        norm(x) in t
        for x in NON_FRAGRANCE
    )


def jsonld_products(soup):
    out = []

    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            data = json.loads(
                script.get_text()
            )
        except Exception:
            continue

        stack = (
            data
