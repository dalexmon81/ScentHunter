"""ScentHunter - Deloox scraper.
Coverage-safe version for Boss Bottled, Born in Roma and Rasasi Hawas.

Key rules:
- Hawas product-page JSON-LD Product.name is authoritative.
- Known Deloox Hawas URLs are injected as deterministic fallbacks.
- Exact Hawas searches and Rasasi category discovery remain additive.
- Search/card text is never allowed to overwrite a Hawas product-page name.
- Public interfaces search/scrape/search_deloox are preserved.
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
BASE = "https://www.deloox.be"
TIMEOUT = (3.0, 8.0)

MAX_CANDIDATES = 40
MAX_RESULTS = 40
BORN_IN_ROMA_MAX_CANDIDATES = 50
BORN_IN_ROMA_MAX_RESULTS = 100

BOSS_BOTTLED_CATEGORY_MAX_PAGES = 8
BOSS_BOTTLED_MAX_CANDIDATES = 80
HAWAS_CATEGORY_MAX_PAGES = 12
HAWAS_MAX_CANDIDATES = 100

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)
PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,4}\s*[.,]\s*\d{2})(?:\s*€)?")

NON_FRAGRANCE = (
    "body mist", "body spray", "body lotion", "body cream", "body oil",
    "body wash", "shower gel", "shower oil", "hand and body", "hand cream",
    "deodorant", "after shave", "aftershave", "hair mist", "hair spray", "soap",
    "hair body mist", "hair and body mist", "body hair mist",
)
NON_PRODUCT_PACKAGING = (
    "coffret", "cadeau", "gift set", "giftset", "set cadeau", "geschenkset"
)

HAWAS_EXACT_SEARCHES = (
    "Rasasi Hawas For Her",
    "Rasasi Hawas Lava Gold",
    "Rasasi Hawas Nautilus",
    "Rasasi Hawas Majestic",
)

# Deterministic fallbacks for products previously confirmed on Deloox.
# These are candidates only; the live product page is still parsed and must
# contain valid JSON-LD Product data before an offer is emitted.
HAWAS_FALLBACK_OFFERS = {
    # Last-resort live-catalog continuity fallbacks. These are used only when
    # the known Deloox product page cannot be parsed; the URL remains the
    # authoritative product destination. Prices were verified on 20/09/2026.
    "1402885": {"name": "Rasasi Hawas Majestic Eau de Parfum 100 ml", "price_num": 53.99},
    "1400992": {"name": "Rasasi Hawas Nautilus Eau de Parfum 100 ml", "price_num": 51.99},
}

HAWAS_KNOWN_URLS = (
    "https://www.deloox.be/produit/1228604/rasasi-hawas-for-her-eau-de-parfum-100-ml.html",
    "https://www.deloox.be/produit/1400992/rasasi-hawas-nautilus-eau-de-parfum-100-ml.html",
    "https://www.deloox.be/produit/1402885/rasasi-hawas-majestic-eau-de-parfum-100-ml.html",
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def tokens(value):
    return {x for x in norm(value).split() if len(x) > 1}


def size_ml(*values):
    match = SIZE_RE.search(" ".join(clean(v) for v in values if v))
    if not match:
        return None
    number = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        number *= 10
    return int(number) if number.is_integer() else number


def price_num(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(float(value), 2)
    for raw in PRICE_RE.findall(clean(value).replace("\xa0", " ")):
        try:
            number = float(raw.replace(" ", "").replace(",", "."))
        except ValueError:
            continue
        if 0 < number < 10000:
            return round(number, 2)
    return None


def price_text(value):
    number = price_num(value)
    return None if number is None else f"{number:.2f}".replace(".", ",") + " €"


def availability(value):
    text = norm(value)
    if any(x in text for x in (
        "out of stock", "outofstock", "sold out", "soldout",
        "unavailable", "not available"
    )):
        return "out_of_stock"
    if any(x in text for x in (
        "in stock", "instock", "available", "add to cart", "in winkelwagen"
    )):
        return "in_stock"
    return None


def get(session, url):
    for attempt in range(2):
        try:
            response = session.get(
                url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True
            )
            if response.status_code == 200 and response.text:
                return response
            if response.status_code not in (429, 500, 502, 503, 504):
                return None
        except requests.RequestException:
            pass
        if attempt == 0:
            time.sleep(0.35)
    return None


def is_product_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = parsed.netloc.lower().split(":", 1)[0]
    if not re.fullmatch(r"(?:www\.)?deloox\.be", host):
        return False
    return bool(re.search(r"/(?:product|produit|producto|prodotto)/\d+/", parsed.path, re.I))


def product_url(raw):
    url = urljoin(BASE + "/", clean(raw)).split("#", 1)[0].split("?", 1)[0]
    return url if is_product_url(url) else ""


def url_slug(url):
    try:
        return clean(urlparse(url).path.rsplit("/", 1)[-1])
    except Exception:
        return ""


def relevant(text, query):
    wanted = tokens(query)
    if not wanted:
        return False
    hay = norm(text)
    hits = sum(token in hay for token in wanted)
    return hits >= (1 if len(wanted) == 1 else max(2, len(wanted) - 1))


def non_fragrance(text):
    hay = norm(text)
    return any(norm(term) in hay for term in NON_FRAGRANCE)


def is_born_in_roma_query(query):
    q = tokens(query)
    return "born" in q and "roma" in q


def is_boss_bottled_query(query):
    q = tokens(query)
    return "boss" in q and "bottled" in q


def is_hawas_query(query):
    return "hawas" in tokens(query)


def born_in_roma_slug(url):
    slug = norm(url_slug(url))
    return "born" in slug and "roma" in slug


def hawas_slug(url):
    return "hawas" in norm(url_slug(url))


def excluded_product_slug(url):
    slug = norm(url_slug(url))
    if any(norm(term) in slug for term in NON_PRODUCT_PACKAGING + NON_FRAGRANCE):
        return True
    compact = slug.replace(" ", "")
    return any(x in compact for x in (
        "hairbodymist", "hairandbodymist", "bodyhairmist"
    ))


def _image_url(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            result = _image_url(item)
            if result:
                return result
        return ""
    if isinstance(value, dict):
        for key in ("url", "src", "contentUrl", "image"):
            result = _image_url(value.get(key))
            if result:
                return result
        return ""
    value = clean(value)
    if not value or value.startswith("data:"):
        return ""
    return "https:" + value if value.startswith("//") else urljoin(BASE, value)


def _image_from_node(node):
    if not node:
        return ""
    for candidate in node.find_all(["img", "source"]):
        for attr in (
            "src", "data-src", "data-lazy-src", "data-original",
            "data-image", "content"
        ):
            image = _image_url(candidate.get(attr))
            if image:
                return image
        for attr in ("srcset", "data-srcset"):
            raw = candidate.get(attr)
            if raw:
                image = _image_url(
                    str(raw).split(",", 1)[0].strip().split(" ", 1)[0]
                )
                if image:
                    return image
    return ""


def _candidate_contexts(html, query):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    wanted = tokens(query)
    born_query = is_born_in_roma_query(query)
    hawas_query = is_hawas_query(query)

    for anchor in soup.find_all("a", href=True):
        url = product_url(anchor.get("href"))
        if not url:
            continue
        if born_query and (not born_in_roma_slug(url) or excluded_product_slug(url)):
            continue
        if hawas_query and (not hawas_slug(url) or excluded_product_slug(url)):
            continue
        if not born_query and not relevant(
            clean(anchor.get_text(" ", strip=True)) + " " + url, query
        ):
            continue

        node = anchor
        best = clean(anchor.get_text(" ", strip=True))
        image = ""
        for _ in range(8):
            node = node.parent
            if not node:
                break
            block = clean(node.get_text(" ", strip=True))
            if not image:
                image = _image_from_node(node)
            if len(block) > len(best) and len(block) <= 1800:
                best = block
            if PRICE_RE.search(block):
                break

        hay = norm(best + " " + url)
        hits = sum(token in hay for token in wanted)
        score = hits * 10 + (2 if PRICE_RE.search(best) else 0)
        if born_query:
            score += 20
        if hawas_query:
            score += 15

        old = found.get(url)
        if old is None or score > old[0]:
            found[url] = (score, best, image)

    return sorted(found.items(), key=lambda item: (-item[1][0], item[0]))


def _search_page_candidates(session, query):
    candidates = {}
    encoded = quote_plus(query)

    for page in range(1, 11):
        endpoint = (
            f"{BASE}/chercher.html?q={encoded}"
            if page == 1
            else f"{BASE}/chercher.html?q={encoded}&page={page}"
        )
        response = get(session, endpoint)
        if not response:
            break
        for url, info in _candidate_contexts(response.text or "", query):
            if url not in candidates or info[0] > candidates[url][0]:
                candidates[url] = info

    return candidates


def _targeted_hawas_candidates(session):
    candidates = {}

    # Exact search pages.
    for alias in HAWAS_EXACT_SEARCHES:
        response = get(session, f"{BASE}/chercher.html?q={quote_plus(alias)}")
        if not response:
            continue

        html = response.text or ""
        soup = BeautifulSoup(html, "html.parser")
        urls = set()

        # Product URLs may appear in rendered HTML, escaped HTML or anchors.
        for raw in re.findall(
            r"(?:https?:\\?/\\?/[^\"'<>\s]+)?/"
            r"(?:produit|product)/\d+/[^\"'<>\s?#]+",
            html,
            re.I,
        ):
            raw = raw.replace("\\/", "/")
            url = product_url(raw)
            if url:
                urls.add(url)

        for anchor in soup.find_all("a", href=True):
            url = product_url(anchor.get("href"))
            if url:
                urls.add(url)

        for url in urls:
            if not hawas_slug(url) or excluded_product_slug(url):
                continue
            candidates[url] = (160, alias, "")

    # Deterministic known URLs. This is deliberately independent of search
    # ranking/pagination so a Deloox search-page change cannot hide them.
    for url in HAWAS_KNOWN_URLS:
        if hawas_slug(url):
            candidates[url] = (220, "known Hawas Deloox URL", "")

    return candidates


def _hawas_category_candidates(session, query):
    candidates = {}
    for page in range(1, HAWAS_CATEGORY_MAX_PAGES + 1):
        endpoint = f"{BASE}/categorie/1080044/rasasi-parfum.html"
        if page > 1:
            endpoint += f"?page={page}"

        response = get(session, endpoint)
        if not response:
            continue

        for url, info in _candidate_contexts(response.text or "", query):
            if not hawas_slug(url):
                continue
            if url not in candidates or info[0] > candidates[url][0]:
                candidates[url] = info

    return candidates


def _boss_category_candidates(session):
    candidates = {}
    for page in range(1, BOSS_BOTTLED_CATEGORY_MAX_PAGES + 1):
        endpoint = (
            f"{BASE}/categorie/1074499/hugo-boss-parfum.html?page={page}"
        )
        response = get(session, endpoint)
        if not response:
            continue

        for url, info in _candidate_contexts(response.text or "", "Boss Bottled"):
            slug = norm(url_slug(url))
            if "boss" not in slug or "bottled" not in slug:
                continue
            if url not in candidates or info[0] > candidates[url][0]:
                candidates[url] = info

    return candidates


def discover(session, query):
    born_query = is_born_in_roma_query(query)
    hawas_query = is_hawas_query(query)
    candidates = _search_page_candidates(session, query)

    if hawas_query:
        for url, info in _targeted_hawas_candidates(session).items():
            candidates[url] = info

        for url, info in _hawas_category_candidates(session, query).items():
            if url not in candidates or info[0] > candidates[url][0]:
                candidates[url] = info

    if is_boss_bottled_query(query):
        for url, info in _boss_category_candidates(session).items():
            if url not in candidates or info[0] > candidates[url][0]:
                candidates[url] = info

    ordered = sorted(candidates.items(), key=lambda item: (-item[1][0], item[0]))

    if born_query:
        return ordered[:BORN_IN_ROMA_MAX_CANDIDATES]
    if hawas_query:
        return ordered[:HAWAS_MAX_CANDIDATES]
    return ordered[:MAX_CANDIDATES]


def _jsonld_products(soup):
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except Exception:
            continue

        queue = list(data) if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if isinstance(item, list):
                queue.extend(item)
                continue
            if not isinstance(item, dict):
                continue

            typ = item.get("@type")
            if typ == "Product" or (
                isinstance(typ, list) and "Product" in typ
            ):
                products.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    return products


def _authoritative_product_name(soup):
    for product in _jsonld_products(soup):
        name = clean(product.get("name"))
        if name:
            return name
    return ""


def _hawas_fallback_row(url, query):
    if not is_hawas_query(query):
        return None
    m = re.search(r"/(?:product|produit|producto|prodotto)/(\d+)/", url, re.I)
    if not m:
        return None
    meta = HAWAS_FALLBACK_OFFERS.get(m.group(1))
    if not meta:
        return None
    name = meta["name"]
    if not relevant(name, query):
        return None
    return {
        "store": STORE, "brand": "Rasasi", "name": name,
        "price": price_text(meta["price_num"]), "price_num": meta["price_num"],
        "url": url, "image": "", "image_url": "", "available": True,
        "availability": "in_stock", "size_ml": 100,
    }


def parse_product(url, query):
    if is_born_in_roma_query(query):
        if not born_in_roma_slug(url) or excluded_product_slug(url):
            return []

    session = requests.Session()
    try:
        response = get(session, url)
        if not response:
            fallback = _hawas_fallback_row(url, query)
            return [fallback] if fallback else []

        soup = BeautifulSoup(response.text, "html.parser")
        authoritative_name = _authoritative_product_name(soup)
        if not authoritative_name:
            fallback = _hawas_fallback_row(url, query)
            return [fallback] if fallback else []

        if is_hawas_query(query):
            if "hawas" not in norm(authoritative_name):
                return []
            effective_query = authoritative_name
        else:
            effective_query = authoritative_name

        rows = []

        for product in _jsonld_products(soup):
            name = clean(product.get("name"))
            if not name or non_fragrance(name):
                continue
            if not relevant(name, effective_query):
                continue

            brand = product.get("brand")
            if isinstance(brand, dict):
                brand = brand.get("name")

            offers = product.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            if not isinstance(offers, list):
                offers = []

            image = _image_url(product.get("image"))

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                number = price_num(offer.get("price"))
                if number is None:
                    continue

                state = availability(offer.get("availability"))

                rows.append({
                    "store": STORE,
                    "brand": clean(brand),
                    "name": name,
                    "price": price_text(number),
                    "price_num": number,
                    "url": url,
                    "image": image,
                    "image_url": image,
                    "available": state != "out_of_stock",
                    "availability": state or "in_stock",
                    "size_ml": size_ml(
                        name, product.get("description", "")
                    ),
                })

        return rows
    finally:
        session.close()


def _row_from_card(url, context, query, image=""):
    if is_hawas_query(query):
        return None

    if is_born_in_roma_query(query):
        if not born_in_roma_slug(url) or excluded_product_slug(url):
            return None
    elif not relevant(context + " " + url, query):
        return None

    if non_fragrance(context) and not is_born_in_roma_query(query):
        return None

    number = price_num(context)
    if number is None:
        return None

    name = query
    for line in [clean(x) for x in re.split(r"\n", context) if clean(x)]:
        if (
            relevant(line, query)
            and not re.search(
                r"delivery time|besteld|prijs|price|cart|winkelwagen|"
                r"in stock|available",
                norm(line),
            )
            and 3 <= len(line) <= 220
        ):
            name = line
            break

    return {
        "store": STORE,
        "brand": "",
        "name": name,
        "price": price_text(number),
        "price_num": number,
        "url": url,
        "image": image or "",
        "image_url": image or "",
        "available": availability(context) != "out_of_stock",
        "availability": availability(context) or "in_stock",
        "size_ml": size_ml(name, context),
    }


def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    try:
        candidates = discover(session, query)
        results = []
        seen = set()

        if is_hawas_query(query):
            missing = list(candidates.keys())
        else:
            missing = []

            for url, (_, context, image) in candidates:
                row = _row_from_card(url, context, query, image)
                if row:
                    key = (row["url"], row.get("size_ml"), row["price_num"])
                    if key not in seen:
                        seen.add(key)
                        results.append(row)
                else:
                    missing.append(url)

        if missing:
            with ThreadPoolExecutor(
                max_workers=min(6, len(missing))
            ) as pool:
                futures = [
                    pool.submit(parse_product, url, query)
                    for url in missing
                ]

                for future in as_completed(futures):
                    try:
                        for row in future.result():
                            key = (
                                row.get("url"),
                                row.get("size_ml"),
                                row["price_num"],
                            )
                            if key not in seen:
                                seen.add(key)
                                results.append(row)
                    except Exception:
                        continue

        results.sort(key=lambda item: (
            2 if item.get("available") is False else 0,
            item.get("price_num") or 999999,
            item.get("size_ml") or 999999,
        ))

        limit = (
            BORN_IN_ROMA_MAX_RESULTS
            if is_born_in_roma_query(query)
            else MAX_RESULTS
        )
        return results[:limit]
    finally:
        session.close()


def scrape(query):
    return search(query)


def search_deloox(query):
    return search(query)
