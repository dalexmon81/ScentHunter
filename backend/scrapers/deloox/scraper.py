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

# IMPORTANT:
# Keep the normal candidate limit unchanged.
MAX_CANDIDATES = 40

# Born in Roma has several real variants/sizes on Deloox.
# After filtering obvious non-fragrance products, allow a small
# additional margin so late-page products such as Ivory are not cut.
BORN_IN_ROMA_MAX_CANDIDATES = 50

MAX_RESULTS = 40

# Born in Roma has multiple real variants and multiple package sizes.
# Keep the generic cap unchanged, but do not truncate this family before
# all discovered Deloox variants can reach the central matcher.
BORN_IN_ROMA_MAX_RESULTS = 100


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,"
        "application/json;q=0.9,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


SIZE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
    re.I,
)


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
    # Deloox can expose Valentino Born in Roma Hair & Body Mist
    # listings whose URL/title uses the combined wording. Keep these
    # variants explicitly excluded from fragrance results.
    "hair body mist",
    "hair and body mist",
    "body hair mist",
)


# Products that may contain the family name in their URL/card,
# but are NOT the perfume itself.
NON_PRODUCT_PACKAGING = (
    "coffret",
    "cadeau",
    "gift set",
    "giftset",
    "set cadeau",
    "geschenkset",
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


def url_slug(url):
    try:
        return clean(
            urlparse(url).path.rsplit("/", 1)[-1]
        )
    except Exception:
        return ""


def is_born_in_roma_query(query):
    q = tokens(query)

    return (
        "born" in q
        and "roma" in q
    )


def born_in_roma_slug(url):
    """
    True only when the actual Deloox product URL identifies
    the Born in Roma family.

    This is intentionally based on the URL slug, not the large
    surrounding search-card text. The latter can contain text
    from neighbouring products.
    """
    slug = norm(url_slug(url))

    return (
        "born" in slug
        and "roma" in slug
    )


def excluded_product_slug(url):
    """
    Reject obvious non-product packaging/body products from the
    Born in Roma candidate pool before MAX_CANDIDATES is applied.
    """
    slug = norm(url_slug(url))

    if any(
        norm(term) in slug
        for term in NON_PRODUCT_PACKAGING
    ):
        return True

    if any(
        norm(term) in slug
        for term in NON_FRAGRANCE
    ):
        return True

    # Defensive handling for compact URL spellings such as
    # hair-body-mist / hairandbodymist. This remains limited to the
    # existing Deloox non-fragrance exclusion stage.
    compact_slug = slug.replace(" ", "")
    if any(
        marker in compact_slug
        for marker in (
            "hairbodymist",
            "hairandbodymist",
            "bodyhairmist",
        )
    ):
        return True

    return False


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


def _image_url(value):
    if isinstance(value, (list, tuple)):
        for item in value:
            image = _image_url(item)
            if image:
                return image

        return ""

    if isinstance(value, dict):
        for key in (
            "url",
            "src",
            "contentUrl",
            "image",
        ):
            image = _image_url(
                value.get(key)
            )

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

    # Read the product-card image from the HTML already downloaded
    # for search. This avoids an extra HTTP request for every result.
    for candidate in node.find_all(
        ["img", "source"]
    ):
        for attr in (
            "src",
            "data-src",
            "data-lazy-src",
            "data-original",
            "data-image",
            "content",
        ):
            image = _image_url(
                candidate.get(attr)
            )

            if image:
                return image

        for attr in (
            "srcset",
            "data-srcset",
        ):
            raw = candidate.get(attr)

            if not raw:
                continue

            first = (
                str(raw)
                .split(",", 1)[0]
                .strip()
                .split(" ", 1)[0]
            )

            image = _image_url(first)

            if image:
                return image

    return ""


def _candidate_contexts(html, query):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    q = tokens(query)
    born_query = is_born_in_roma_query(query)
    found = {}

    # -------------------------------------------------------------
    # Born in Roma: collect the REAL Deloox product URLs directly
    # from the HTML first. This is deliberately independent from
    # the surrounding search-card text, which Deloox can merge with
    # neighbouring products.
    # -------------------------------------------------------------
    direct_urls = set()

    if born_query:
        for a in soup.find_all("a", href=True):
            url = product_url(a.get("href"))
            if url:
                direct_urls.add(url)

        # Safety net for URLs embedded in HTML/JSON attributes where
        # BeautifulSoup does not expose them as normal anchor hrefs.
        for raw in re.findall(
            r"(?:https?:\\/\\/[^\"'<>\\s]+)?/produit/\\d+/[^\"'<>\\s]+",
            html,
            flags=re.I,
        ):
            raw = raw.replace("\\/", "/")
            url = product_url(raw)
            if url:
                direct_urls.add(url)

        # Keep ONLY Born in Roma perfume products.
        direct_urls = {
            url
            for url in direct_urls
            if born_in_roma_slug(url)
            and not excluded_product_slug(url)
        }

    # Normal card extraction.
    for a in soup.find_all(
        "a",
        href=True,
    ):
        url = product_url(a.get("href"))

        if not url:
            continue

        if born_query:
            if url not in direct_urls:
                continue
        elif not relevant(
            clean(a.get_text(" ", strip=True)) + " " + url,
            query,
        ):
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

        if born_query:
            hits = sum(
                t in norm(
                    best + " " + url
                )
                for t in q
            )

            score = (
                max(hits, len(q)) * 10
                + (2 if PRICE_RE.search(best) else 0)
                + 20
            )
        else:
            hits = sum(
                t in norm(best + " " + url)
                for t in q
            )

            score = (
                hits * 10
                + (2 if PRICE_RE.search(best) else 0)
            )

        old = found.get(url)
        if old is None or score > old[0]:
            found[url] = (
                score,
                best,
                card_image,
            )

    # -------------------------------------------------------------
    # IMPORTANT FALLBACK:
    # If Deloox exposes a valid Born in Roma product URL in HTML but
    # not as a normal <a href>, still create a candidate. The URL is
    # enough to identify the product; product-page parsing can later
    # supply price/image/availability when the card has no usable data.
    # -------------------------------------------------------------
    if born_query:
        for url in direct_urls:
            if url in found:
                continue

            # Try to locate a nearby HTML fragment for price/image.
            context = ""
            image = ""

            marker = url.split("/produit/", 1)[-1]
            pos = html.lower().find(marker.lower())

            if pos >= 0:
                fragment = html[max(0, pos - 6000):pos + 12000]
                frag_soup = BeautifulSoup(
                    fragment,
                    "html.parser",
                )
                context = clean(
                    frag_soup.get_text(
                        " ",
                        strip=True,
                    )
                )
                image = _image_from_node(frag_soup)

            found[url] = (
                40,
                context,
                image,
            )

        ordered = sorted(
            found.items(),
            key=lambda x: (
                -x[1][0],
                x[0],
            ),
        )

        return ordered[:BORN_IN_ROMA_MAX_CANDIDATES]

    return sorted(
        found.items(),
        key=lambda x: (
            -x[1][0],
            len(x[0]),
            x[0],
        ),
    )[:MAX_CANDIDATES]


def _row_from_card(
    url,
    context,
    query,
    image="",
):
    # For Born in Roma, verify the URL itself rather than relying
    # exclusively on the surrounding card text.
    if is_born_in_roma_query(query):
        if not born_in_roma_slug(url):
            return None

        if excluded_product_slug(url):
            return None

    elif not relevant(
        context + " " + url,
        query,
    ):
        return None

    if non_fragrance(context):
        # A surrounding card may contain text from another product.
        # For Born in Roma we already have URL-level exclusion above,
        # so do not reject a valid product merely because the parent
        # container contains neighbouring body-product text.
        if not is_born_in_roma_query(query):
            return None

    lines = [
        clean(x)
        for x in re.split(
            r"\n|(?=Delivery time\s*:)|(?=our price\s)|"
            r"(?=onze prijs\s)|(?=nostro prezzo\s)",
            context,
        )
        if clean(x)
    ]

    name = ""

    for line in lines:
        candidate = line

        # Repair obvious mojibake.
        if any(
            marker in candidate
            for marker in (
                "Ã",
                "Â",
                "â€",
                "ðŸ",
            )
        ):
            try:
                repaired = (
                    candidate
                    .encode("cp1252")
                    .decode("utf-8")
                )

                if repaired != candidate:
                    candidate = repaired

            except (
                UnicodeEncodeError,
                UnicodeDecodeError,
            ):
                pass

        # Remove retailer presentation metadata.
        candidate = re.sub(
            r"\s+(?:en stock|in stock|available|"
            r"disponible|beschikbaar)\b.*$",
            "",
            candidate,
            flags=re.I,
        )

        candidate = re.sub(
            r"\s+(?:notre prix|our price|onze prijs|"
            r"nostro prezzo)\b.*$",
            "",
            candidate,
            flags=re.I,
        )

        candidate = re.sub(
            r"\s+(?:d[ée]lai de livraison|delivery time|"
            r"levertijd|tempi di consegna)\s*:\s*.*$",
            "",
            candidate,
            flags=re.I,
        ).strip()

        if (
            relevant(
                candidate,
                query,
            )
            and not re.search(
                r"delivery time|besteld|prijs|price|"
                r"cart|winkelwagen|in stock|available",
                norm(candidate),
            )
            and 3 <= len(candidate) <= 220
        ):
            name = candidate
            break

    # -------------------------------------------------------------
    # If Deloox's parent card is polluted by neighbouring products,
    # derive the actual title from the product URL.
    #
    # This is particularly important for:
    #   - Ivory Uomo
    #   - Ivory Donna
    #   - The Gold Uomo
    #   - The Gold Donna
    # -------------------------------------------------------------
    if is_born_in_roma_query(query):
        slug = url_slug(url)

        title = re.sub(
            r"^\d+[-_]",
            "",
            slug,
            flags=re.I,
        )

        title = re.sub(
            r"[-_]+",
            " ",
            title,
        )

        # Remove the Valentino prefix.
        title = re.sub(
            r"^valentino\s+",
            "",
            title,
            flags=re.I,
        )

        # Keep the product title before size/concentration tail.
        title = re.split(
            r"\b(?:eau|parfum|toilette|spray|vaporisateur)\b",
            title,
            maxsplit=1,
            flags=re.I,
        )[0]

        title = re.sub(
            r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl)\b.*$",
            "",
            title,
            flags=re.I,
        )

        title = clean(title)

        if (
            born_in_roma_slug(url)
            and title
            and len(title) >= 5
        ):
            # Reconstruct readable capitalization without trying
            # to editorially rename the product.
            name = title.title()

    name = name or query

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
        "image": image or "",
        "image_url": image or "",
        "available": (
            state != "out_of_stock"
        ),
        "availability": (
            state or "in_stock"
        ),
        "size_ml": size_ml(
            name,
            context,
        ),
    }


def discover(
    session,
    query,
):
    """Discover Deloox product URLs.

    Born in Roma is handled directly from the search-page HTML.
    Deloox search cards contain merged/neighbouring product text, so
    card-based relevance is not reliable for this family. The actual
    /produit/<id>/<slug>.html URL is the authoritative product identity.
    """
    encoded = quote_plus(query)
    q = tokens(query)
    born_query = is_born_in_roma_query(query)

    candidates = {}
    seen_pages = set()

    for page in range(1, 11):
        if page == 1:
            endpoint = f"{BASE}/chercher.html?q={encoded}"
        else:
            endpoint = f"{BASE}/chercher.html?q={encoded}&page={page}"

        r = get(session, endpoint)
        if not r or r.url in seen_pages:
            break
        seen_pages.add(r.url)

        html = r.text or ""

        if born_query:
            # Direct URL extraction. Do NOT depend on <a> structure,
            # card text, price presence, or neighbouring DOM nodes.
            raw_urls = re.findall(
                r"(?:https?:\\?/\\?/[^\"'<>\s]+)?/produit/\d+/[^\"'<>\s?#]+",
                html,
                flags=re.I,
            )

            for raw in raw_urls:
                raw = raw.replace("\\/", "/")
                if raw.startswith("/"):
                    url = urljoin(BASE + "/", raw)
                elif raw.startswith("http"):
                    url = raw
                else:
                    continue

                url = url.split("#", 1)[0].split("?", 1)[0]
                if not is_product_url(url):
                    continue
                if not born_in_roma_slug(url):
                    continue
                if excluded_product_slug(url):
                    continue

                # Fixed high score: this candidate was identified by its
                # real product URL, not by surrounding search-card text.
                candidates[url] = (
                    100,
                    url_slug(url),
                    "",
                )

            # Also inspect ordinary anchors as a second, independent
            # extraction path. This catches HTML-encoded/attribute URLs
            # that regex may not see.
            soup = BeautifulSoup(html, "html.parser")
            for a in soup.find_all("a", href=True):
                url = product_url(a.get("href"))
                if not url:
                    continue
                if not born_in_roma_slug(url):
                    continue
                if excluded_product_slug(url):
                    continue

                text = clean(a.get_text(" ", strip=True))
                old = candidates.get(url)
                if old is None:
                    candidates[url] = (100, text or url_slug(url), "")
                elif text and len(text) > len(old[1]):
                    candidates[url] = (100, text, old[2])

            continue

        # Historical generic discovery path.
        page_candidates = _candidate_contexts(html, query)
        for url, info in page_candidates:
            if url not in candidates or info[0] > candidates[url][0]:
                candidates[url] = info

        # Existing special fallbacks remain available below.

    # Existing bounded catalog fallbacks for non-Born queries.
    if not born_query:
        if {"liquid", "brun"} <= q and ({"limited", "edition"} & q):
            r = get(
                session,
                f"{BASE}/en/category/1132834/liquid-brun.html",
            )
            if r:
                for url, info in _candidate_contexts(r.text, query):
                    if url not in candidates or info[0] > candidates[url][0]:
                        candidates[url] = info

        if "hawas" in q:
            r = get(
                session,
                f"{BASE}/categorie/1080044/rasasi-parfum.html",
            )
            if r:
                for url, info in _candidate_contexts(r.text, query):
                    if url not in candidates or info[0] > candidates[url][0]:
                        candidates[url] = info

        for endpoint in (
            f"{BASE}/en/category/1103659/fragrances.html",
            f"{BASE}/en/category/1121334/french-avenue-mens-fragrances.html",
        ):
            r = get(session, endpoint)
            if not r:
                continue
            for url, info in _candidate_contexts(r.text, query):
                if url not in candidates or info[0] > candidates[url][0]:
                    candidates[url] = info

    ordered = sorted(
        candidates.items(),
        key=lambda x: (-x[1][0], x[0]),
    )

    if born_query:
        return ordered[:BORN_IN_ROMA_MAX_CANDIDATES]

    return ordered[:MAX_CANDIDATES]

def parse_product(
    url,
    query,
):
    # Extra safety: never parse an excluded Born in Roma URL.
    if is_born_in_roma_query(query):
        if not born_in_roma_slug(url):
            return []

        if excluded_product_slug(url):
            return []

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

        # Deloox search/category cards can contain text from neighbouring
        # products. The product page JSON-LD Product.name is the
        # authoritative identity and must override the polluted card name.
        authoritative_name = ""
        for script in soup.find_all(
            "script",
            type="application/ld+json",
        ):
            try:
                data = json.loads(
                    script.string or script.get_text()
                )
            except (
                json.JSONDecodeError,
                TypeError,
            ):
                continue

            queue = (
                list(data)
                if isinstance(data, list)
                else [data]
            )

            while queue:
                item = queue.pop(0)

                if isinstance(item, list):
                    queue.extend(item)
                    continue

                if not isinstance(item, dict):
                    continue

                typ = item.get("@type")
                is_product = (
                    typ == "Product"
                    or (
                        isinstance(typ, list)
                        and "Product" in typ
                    )
                )

                if is_product:
                    candidate_name = clean(item.get("name"))
                    if candidate_name:
                        authoritative_name = candidate_name
                        break

                graph = item.get("@graph")
                if isinstance(graph, list):
                    queue.extend(graph)

            if authoritative_name:
                break

        effective_query = authoritative_name or query

        rows = []

        for p in jsonld_products(soup):
            name = clean(
                p.get("name")
                or query
            )

            if (
                not relevant(
                    name,
                    effective_query,
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

                image = _image_url(
                    p.get("image")
                )

                rows.append(
                    {
                        "store": STORE,
                        "brand": clean(
                            brand
                        ),
                        "name": name,
                        "price": price_text(n),
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
            image,
        ) in candidates:

            row = _row_from_card(
                url,
                context,
                query,
                image,
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

        # Product pages are fetched only for cards that did not
        # produce a usable price/row.
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

        result_limit = (
            BORN_IN_ROMA_MAX_RESULTS
            if is_born_in_roma_query(query)
            else MAX_RESULTS
        )
        return results[:result_limit]

    finally:
        session.close()


def scrape(query):
    return search(query)


def search_deloox(query):
    return search(query)
