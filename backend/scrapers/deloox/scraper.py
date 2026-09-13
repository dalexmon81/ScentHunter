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
    return re.sub(r"[^a-z0-9]+", " ", clean(v).lower()).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def size_ml(*values):
    m = SIZE_RE.search(" ".join(clean(x) for x in values if x))
    if not m:
        return None

    n = float(m.group(1).replace(",", "."))

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
            n = float(raw.replace(",", "."))
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

            if r.status_code not in (429, 500, 502, 503, 504):
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
        urljoin(BASE + "/", clean(raw))
        .split("#", 1)[0]
        .split("?", 1)[0]
    )

    return url if is_product_url(url) else ""


def relevant(text, query):
    q = tokens(query)
    hay = norm(text)

    if not q:
        return False

    hits = sum(t in hay for t in q)

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
            data = json.loads(script.get_text())
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            typ = item.get("@type")

            if (
                typ == "Product"
                or (
                    isinstance(typ, list)
                    and "Product" in typ
                )
            ):
                out.append(item)

            if isinstance(item.get("@graph"), list):
                stack.extend(item["@graph"])

    return out


def _candidate_contexts(html, query):
    soup = BeautifulSoup(html, "html.parser")
    q = tokens(query)
    found = {}

    for a in soup.find_all("a", href=True):
        url = product_url(a.get("href"))

        if not url:
            continue

        node = a
        best = clean(
            a.get_text(" ", strip=True)
        )

        for _ in range(7):
            node = node.parent

            if not node:
                break

            text = clean(
                node.get_text(
                    " ",
                    strip=True,
                )
            )

            if (
                len(text) > len(best)
                and len(text) <= 1800
            ):
                best = text

            if PRICE_RE.search(text):
                break

        blob = norm(best + " " + url)
        hits = sum(t in blob for t in q)

        # IMPORTANT:
        # Do not keep weak candidates that only partially match a
        # multi-word query. For example, when searching
        # "Liquid Brun Limited Edition", a normal "Liquid Brun"
        # product must NOT be allowed to satisfy discovery.
        #
        # The old condition only rejected candidates with zero hits.
        # That caused discover() to stop after finding generic
        # "Liquid Brun" products before reaching the category page
        # containing the Limited Edition.
        if q and not relevant(best + " " + url, query):
            continue

        old = found.get(url)

        score = hits * 10 + (
            2 if PRICE_RE.search(best) else 0
        )

        if old is None or score > old[0]:
            found[url] = (
                score,
                best,
            )

    return sorted(
        found.items(),
        key=lambda x: (
            -x[1][0],
            len(x[0]),
            x[0],
        ),
    )[:MAX_CANDIDATES]


def _row_from_card(url, context, query):
    if (
        not relevant(
            context + " " + url,
            query,
        )
        or non_fragrance(context)
    ):
        return None

    # Prefer a product-like line from the card over
    # the whole card text.
    lines = [
        clean(x)
        for x in re.split(
            r"\n|(?=Delivery time\s*:)|(?=our price\s)|(?=onze prijs\s)|(?=nostro prezzo\s)",
            context,
        )
        if clean(x)
    ]

    name = ""

    for line in lines:
        if (
            relevant(line, query)
            and not re.search(
                r"delivery time|besteld|prijs|price|cart|winkelwagen|in stock|available",
                norm(line),
            )
        ):
            if 3 <= len(line) <= 220:
                name = line
                break

    if not name:
        name = query

    size = size_ml(
        name,
        context,
    )

    n = price_num(context)

    if n is None:
        return None

    state = availability(context)

    return {
        "store": STORE,
        "brand": "",
        "name": name,
        "price": price_text(n),
        "price_num": n,
        "url": url,
        "available": state != "out_of_stock",
        "availability": state or "in_stock",
        "size_ml": size,
    }


def discover(session, query):
    encoded = quote_plus(query)

    endpoints = (
        f"{BASE}/en/search?query={encoded}",
        f"{BASE}/en/search?q={encoded}",
        f"{BASE}/en/search?search={encoded}",
        f"https://www.deloox.nl/en/search?query={encoded}",
        f"https://www.deloox.es/en/search?query={encoded}",
    )

    # Search endpoints first; if Deloox resolves the query
    # to a dedicated category page, that page contains exactly
    # the products we need.
    seen_pages = set()
    candidates = {}

    for endpoint in endpoints:
        r = get(session, endpoint)

        if not r or r.url in seen_pages:
            continue

        seen_pages.add(r.url)

        contexts = _candidate_contexts(
            r.text,
            query,
        )

        for url, (score, context) in contexts:
            old = candidates.get(url)

            if old is None or score > old[0]:
                candidates[url] = (
                    score,
                    context,
                )

        if len(candidates) >= 2:
            # For an exact query such as Liquid Brun this is
            # enough and avoids touching unrelated catalog pages.
            #
            # Weak partial matches have already been filtered by
            # _candidate_contexts(), so this no longer prevents
            # the Limited Edition category fallback.
            break

    if candidates:
        return sorted(
            candidates.items(),
            key=lambda x: (
                -x[1][0],
                x[0],
            ),
        )[:MAX_CANDIDATES]

    # Bounded first-party catalog fallback.
    for endpoint in (
        f"{BASE}/en/category/1103659/fragrances.html",
        f"{BASE}/en/category/1121334/french-avenue-mens-fragrances.html",
        "https://www.deloox.nl/en/category/1121334/french-avenue-mens-fragrances.html",
    ):
        r = get(session, endpoint)

        if not r:
            continue

        for url, info in _candidate_contexts(
            r.text,
            query,
        ):
            candidates[url] = info

        if candidates:
            break

    return sorted(
        candidates.items(),
        key=lambda x: (
            -x[1][0],
            x[0],
        ),
    )[:MAX_CANDIDATES]


def parse_product(url, query):
    session = requests.Session()

    try:
        r = get(session, url)

        if not r:
            return []

        soup = BeautifulSoup(
            r.text,
            "html.parser",
        )

        rows = []

        for p in jsonld_products(soup):
            name = clean(
                p.get("name") or query
            )

            if (
                not relevant(name, query)
                or non_fragrance(name)
            ):
                continue

            brand = p.get("brand")

            if isinstance(brand, dict):
                brand = brand.get("name")

            offers = p.get("offers")

            offers = (
                offers
                if isinstance(offers, list)
                else (
                    [offers]
                    if isinstance(offers, dict)
                    else []
                )
            )

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                n = price_num(
                    offer.get("price")
                )

                if n is None:
                    continue

                state = availability(
                    offer.get("availability")
                )

                rows.append(
                    {
                        "store": STORE,
                        "brand": clean(brand),
                        "name": name,
                        "price": price_text(n),
                        "price_num": n,
                        "url": url,
                        "available": state != "out_of_stock",
                        "availability": state or "in_stock",
                        "size_ml": size_ml(
                            name,
                            p.get(
                                "description",
                                "",
                            ),
                        ),
                    }
                )

        return rows

    finally:
        session.close()


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()

    try:
        candidates = discover(
            session,
            query,
        )

        results = []
        seen = set()

        # First use card data already obtained
        # from the discovery page.
        for url, (_, context) in candidates:
            row = _row_from_card(
                url,
                context,
                query,
            )

            if row:
                key = (
                    row["url"],
                    row.get("size_ml"),
                    row["price_num"],
                )

                if key not in seen:
                    seen.add(key)
                    results.append(row)

        # Only fetch product pages for candidates
        # whose card was incomplete.
        missing = [
            (url, info)
            for url, info in candidates
            if not any(
                r.get("url") == url
                for r in results
            )
        ]

        if missing:
            with ThreadPoolExecutor(
                max_workers=min(
                    6,
                    len(missing),
                )
            ) as pool:
                futures = [
                    pool.submit(
                        parse_product,
                        url,
                        query,
                    )
                    for url, _ in missing
                ]

                for f in as_completed(futures):
                    try:
                        for row in f.result():
                            key = (
                                row.get("url"),
                                row.get("size_ml"),
                                row.get("price_num"),
                            )

                            if key not in seen:
                                seen.add(key)
                                results.append(row)

                    except Exception:
                        continue

        results.sort(
            key=lambda x: (
                2
                if x.get("available") is False
                else 0,
                x.get("price_num") or 999999,
                x.get("size_ml") or 999999,
            )
        )

        return results[:MAX_RESULTS]

    finally:
        session.close()


def scrape(query):
    return search(query)


def search_deloox(query):
    return search(query)
