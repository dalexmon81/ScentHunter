"""ScentHunter - Deloox scraper."""
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
TIMEOUT = (2.0, 5.0)
MAX_CANDIDATES = 40
MAX_RESULTS = 40

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

SIZE_RE = re.compile(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b", re.I)

PRICE_RE = re.compile(
    r"(?:€\s*)?(\d{1,4}\s*[.,]\s*\d{2})(?:\s*€)?"
)

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


def clean(v):
    return re.sub(
        r"\s+",
        " ",
        str(v or ""),
    ).strip()


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
    if isinstance(
        v,
        (int, float),
    ) and not isinstance(v, bool):
        return round(float(v), 2)

    text = clean(v).replace(
        "\xa0",
        " ",
    )

    for raw in PRICE_RE.findall(text):
        try:
            n = float(
                raw.replace(" ", "").replace(",", ".")
            )
        except ValueError:
            continue

        if 0 < n < 10000:
            return round(n, 2)

    return None


def price_text(v):
    n = price_num(v)

    if n is None:
        return None

    return (
        f"{n:.2f}".replace(".", ",")
        + " €"
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
    for attempt in range(2):
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )

            if (
                r.status_code == 200
                and r.text
            ):
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

    host = p.netloc.lower().split(
        ":",
        1,
    )[0]

    if not re.fullmatch(
        r"(?:www\.)?deloox\.be",
        host,
    ):
        return False

    return bool(
        re.search(
            r"/(?:product|produit|producto|prodotto)/\d+/",
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

    if not q:
        return False

    hay = norm(text)

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
            if isinstance(data, list)
            else [data]
        )

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

            if isinstance(
                item.get("@graph"),
                list,
            ):
                stack.extend(
                    item["@graph"]
                )

    return out


_CARD_IMAGES = {}


def _image_url(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            image = _image_url(item)
            if image:
                return image
        return ""
    if isinstance(value, dict):
        for key in ("url", "src", "contentUrl", "image"):
            image = _image_url(value.get(key))
            if image:
                return image
        return ""
    value = clean(value)
    if not value or value.startswith("data:"):
        return ""
    if value.startswith("//"):
        return "https:" + value
    return urljoin(BASE, value)


def _image_from_node(node):
    if not node:
        return ""
    for candidate in node.find_all(["img", "source"]):
        for attr in (
            "src", "data-src", "data-lazy-src",
            "data-original", "data-image", "content",
        ):
            image = _image_url(candidate.get(attr))
            if image:
                return image
        for attr in ("srcset", "data-srcset"):
            raw = candidate.get(attr)
            if not raw:
                continue
            first = str(raw).split(",", 1)[0].strip().split(" ", 1)[0]
            image = _image_url(first)
            if image:
                return image
    return ""


def _candidate_contexts(
    html,
    query,
):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    q = tokens(query)
    found = {}

    for a in soup.find_all(
        "a",
        href=True,
    ):
        url = product_url(
            a.get("href")
        )

        if not url:
            continue

        node = a
        card_image = ""

        best = clean(
            a.get_text(
                " ",
                strip=True,
            )
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

            if not card_image:
                card_image = _image_from_node(node)

            if (
                len(text) > len(best)
                and len(text) <= 1800
            ):
                best = text

            if PRICE_RE.search(text):
                break

        if q and not relevant(
            best + " " + url,
            query,
        ):
            continue

        hits = sum(
            t in norm(best + " " + url)
            for t in q
        )

        score = (
            hits * 10
            + (
                2
                if PRICE_RE.search(best)
                else 0
            )
        )

        old = found.get(url)

        if (
            old is None
            or score > old[0]
        ):
            found[url] = (
                score,
                best,
            )
            if card_image:
                _CARD_IMAGES[url] = card_image

    return sorted(
        found.items(),
        key=lambda x: (
            -x[1][0],
            len(x[0]),
            x[0],
        ),
    )[:MAX_CANDIDATES]


def _row_from_card(url, context, query):
    """
    Build a Deloox result from the product URL + search-card data.

    IMPORTANT:
    The surrounding search-card context may contain several neighbouring
    Born in Roma products. The URL slug is therefore the authoritative
    product identity.
    """

    if not is_product_url(url):
        return None

    path = urlparse(url).path
    slug = path.rstrip("/").rsplit("/", 1)[-1]

    # Remove technical .html suffix.
    slug = re.sub(r"\.html?$", "", slug, flags=re.I)

    # Remove leading numeric ID if present.
    slug = re.sub(r"^\d+[-_]", "", slug)

    # Convert URL separators to spaces.
    slug = re.sub(r"[-_]+", " ", slug)

    slug = clean(slug)

    # Reject obvious non-perfume products using the PRODUCT URL itself.
    # Do NOT use the surrounding card context for this decision.
    if non_fragrance(slug):
        return None

    # Reject gift/coffret/set products.
    slug_norm = norm(slug)

    excluded_product_terms = (
        "coffret",
        "cadeau",
        "gift set",
        "giftset",
        "set cadeau",
        "travel set",
        "discovery set",
        "duo",
        "trio",
        "body mist",
        "body spray",
        "hair mist",
        "body lotion",
        "body cream",
        "shower gel",
    )

    if any(
        norm(term) in slug_norm
        for term in excluded_product_terms
    ):
        return None

    # The URL itself MUST identify the requested family.
    # This prevents a neighbouring Born in Roma product in the card
    # context from making an unrelated product look relevant.
    if not relevant(slug, query):
        return None

    # Extract the actual perfume name from the URL.
    #
    # Example:
    # valentino-born-in-roma-uomo-eau-de-toilette-100-ml
    #
    # becomes:
    # valentino born in roma uomo
    name = re.sub(
        r"\b(?:eau\s+de\s+parfum|eau\s+de\s+toilette|"
        r"eau\s+de\s+cologne|eau\s+fraiche|"
        r"extrait\s+de\s+parfum|parfum|perfume|"
        r"toilette|spray|vaporisateur)\b.*$",
        "",
        slug,
        flags=re.I,
    )

    # Remove trailing format information if the previous expression
    # did not already remove it.
    name = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b.*$",
        "",
        name,
        flags=re.I,
    )

    name = clean(name)

    if not name:
        return None

    if not relevant(name, query):
        return None

    if non_fragrance(name):
        return None

    # Brand can safely be recovered from the URL for Valentino.
    brand = ""
    if norm(slug).startswith("valentino "):
        brand = "Valentino"

    # Card context is used ONLY for commercial data.
    card_price = price_num(context)
    card_state = availability(context)

    return {
        "store": STORE,
        "brand": brand,
        "name": name,
        "price": price_text(card_price),
        "price_num": card_price,
        "url": url,
        "image": _CARD_IMAGES.get(url, ""),
        "image_url": _CARD_IMAGES.get(url, ""),
        "available": card_state != "out_of_stock",
        "availability": card_state or "in_stock",
        "size_ml": size_ml(
            slug,
            context,
        ),
    }


def discover(
    session,
    query,
):
    encoded = quote_plus(query)
    q = tokens(query)

    candidates = {}
    seen_pages = set()

    # Deloox.be uses its native search route /chercher.html.
    # The first page shows 12 results and the site's "Charger plus"
    # button loads the next batch with the same URL plus &page=2.
    # Follow subsequent pages until Deloox stops returning new candidates.
    page = 1

    while page <= 10:
        if page == 1:
            endpoint = f"{BASE}/chercher.html?q={encoded}"
        else:
            endpoint = (
                f"{BASE}/chercher.html?q={encoded}"
                f"&page={page}"
            )

        r = get(
            session,
            endpoint,
        )

        if (
            not r
            or r.url in seen_pages
        ):
            break

        seen_pages.add(r.url)

        before = len(candidates)

        for url, info in _candidate_contexts(
            r.text,
            query,
        ):
            if (
                url not in candidates
                or info[0] > candidates[url][0]
            ):
                candidates[url] = info

        # Stop when a subsequent Deloox page adds nothing new.
        if len(candidates) == before:
            break

        page += 1

    # ---------------------------------------------------------
    # FIX SPECIFICO:
    # Liquid Brun Limited Edition
    #
    # Deloox's normal search endpoint returns 404, while the
    # dedicated Liquid Brun category contains the Limited Edition.
    # ---------------------------------------------------------
    if (
        {"liquid", "brun"} <= q
        and (
            {"limited", "edition"}
            & q
        )
    ):
        endpoint = (
            f"{BASE}/en/category/"
            "1132834/liquid-brun.html"
        )

        r = get(
            session,
            endpoint,
        )

        if r:
            for url, info in _candidate_contexts(
                r.text,
                query,
            ):
                if (
                    url not in candidates
                    or info[0] > candidates[url][0]
                ):
                    candidates[url] = info

    # ---------------------------------------------------------
    # FIX: Deloox has retired the /en/search endpoints (they
    # currently return HTTP 404).  Rasasi has a dedicated catalog
    # page which still contains the Hawas products, so use that
    # catalog as the discovery source for Hawas queries.
    # ---------------------------------------------------------
    if "hawas" in q:
        endpoint = (
            f"{BASE}/categorie/"
            "1080044/rasasi-parfum.html"
        )

        r = get(
            session,
            endpoint,
        )

        if r:
            for url, info in _candidate_contexts(
                r.text,
                query,
            ):
                if (
                    url not in candidates
                    or info[0] > candidates[url][0]
                ):
                    candidates[url] = info

    # Existing bounded catalog fallbacks.
    for endpoint in (
        f"{BASE}/en/category/1103659/fragrances.html",
        f"{BASE}/en/category/1121334/french-avenue-mens-fragrances.html",
    ):
        r = get(
            session,
            endpoint,
        )

        if not r:
            continue

        for url, info in _candidate_contexts(
            r.text,
            query,
        ):
            if (
                url not in candidates
                or info[0] > candidates[url][0]
            ):
                candidates[url] = info

    return sorted(
        candidates.items(),
        key=lambda x: (
            -x[1][0],
            x[0],
        ),
    )[:MAX_CANDIDATES]


def parse_product(
    url,
    query,
):
    session = requests.Session()

    try:
        r = get(
            session,
            url,
        )

        if not r:
            return []

        soup = BeautifulSoup(
            r.text,
            "html.parser",
        )

        rows = []

        for p in jsonld_products(soup):
            name = clean(
                p.get("name")
                or query
            )

            if (
                not relevant(
                    name,
                    query,
                )
                or non_fragrance(name)
            ):
                continue

            brand = p.get("brand")

            if isinstance(
                brand,
                dict,
            ):
                brand = brand.get(
                    "name"
                )

            offers = p.get("offers")

            offers = (
                offers
                if isinstance(
                    offers,
                    list,
                )
                else (
                    [offers]
                    if isinstance(
                        offers,
                        dict,
                    )
                    else []
                )
            )

            for offer in offers:
                if not isinstance(
                    offer,
                    dict,
                ):
                    continue

                n = price_num(
                    offer.get("price")
                )

                if n is None:
                    continue

                state = availability(
                    offer.get(
                        "availability"
                    )
                )

                image = _image_url(p.get("image"))

                rows.append(
                    {
                        "store": STORE,
                        "brand": clean(
                            brand
                        ),
                        "name": name,
                        "price": price_text(
                            n
                        ),
                        "price_num": n,
                        "url": url,
                        "image": image,
                        "image_url": image,
                        "available": (
                            state
                            != "out_of_stock"
                        ),
                        "availability": (
                            state
                            or "in_stock"
                        ),
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

        for url, (
            _,
            context,
        ) in candidates:
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

                for f in as_completed(
                    futures
                ):
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
                if x.get("available")
                is False
                else 0,
                x.get(
                    "price_num"
                ) or 999999,
                x.get(
                    "size_ml"
                ) or 999999,
            )
        )

        return results[:MAX_RESULTS]

    finally:
        session.close()


def scrape(query):
    return search(query)


def search_deloox(query):
    return search(query)
