"""Deloox adapter for ScentHunter.

Discovery strategy:
- Use Deloox /en/ catalogue roots.
- Stop early when Deloox returns a suspiciously small HTML shell.
- Inspect category, search and sitemap sources.
- Extract product URLs only when the URL/card/local JSON object matches the query.
- Parse product pages through JSON-LD and visible page content.
- Keep diagnostics useful on Railway without looping through dozens of
  identical 1.5 KB responses.
"""

from __future__ import annotations

import json
import os
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"

TIMEOUT = 10
DISCOVERY_TIMEOUT = 4

# A normal catalogue page should be substantially larger than the tiny
# JavaScript/redirect/challenge shells Deloox can return to plain requests.
MIN_REAL_CATEGORY_BYTES = 10_000

DEBUG_DISCOVERY = os.getenv("DELOOX_DEBUG", "1") != "0"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


CATALOG_URL = BASE_URL + "/en/category/1025540/trending.html?page=60"
CATALOG_FILTER_LINKS = None


def _dbg(stage, **data):
    if not DEBUG_DISCOVERY:
        return
    payload = {"stage": stage, **data}
    print(
        "[DELOOX_DEBUG] "
        + json.dumps(payload, ensure_ascii=False, default=str),
        flush=True,
    )


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", clean(v).lower()),
    ).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def matches(text, q):
    q_tokens = tokens(q)
    return bool(q_tokens) and q_tokens.issubset(tokens(text))


def size_ml(*values):
    m = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        " ".join(clean(x) for x in values),
        re.I,
    )
    if not m:
        return None

    n = float(m.group(1).replace(",", "."))
    if m.group(2).lower() == "cl":
        n *= 10

    return int(n) if n.is_integer() else n


def concentration(*values):
    t = norm(" ".join(clean(x) for x in values))

    if re.search(r"\beau de toilette\b|\bedt\b", t):
        return "Eau de Toilette"

    if re.search(r"\beau de parfum\b|\bedp\b", t):
        return "Eau de Parfum"

    if re.search(r"\bextrait(?: de parfum)?\b", t):
        return "Extrait de Parfum"

    return None


def parse_price(v):
    s = clean(v)
    if not s:
        return None

    # Prefer a value explicitly associated with EUR.
    m = re.search(
        r"€\s*(\d{1,4}(?:[.,]\d{2})?)"
        r"|(\d{1,4}(?:[.,]\d{2})?)\s*€",
        s,
    )

    if not m:
        # Generic fallback for structured JSON-LD numeric values.
        m = re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{2})?)(?!\d)", s)

    if not m:
        return None

    value = next((g for g in m.groups() if g is not None), None)
    if value is None:
        return None

    try:
        return round(float(value.replace(",", ".")), 2)
    except ValueError:
        return None


def _response_kind(response):
    """Classify the HTTP response before trying to parse catalogue data."""
    if response is None:
        return "no_response"

    html = response.text or ""
    low = html.lower()

    if len(response.content or b"") < 5000:
        challenge_terms = (
            "captcha",
            "cloudflare",
            "challenge",
            "access denied",
            "verify you are human",
            "enable javascript",
            "checking your browser",
            "just a moment",
        )
        if any(term in low for term in challenge_terms):
            return "bot_or_challenge"

        soup = BeautifulSoup(html, "html.parser")
        if soup.find_all("script") and not soup.find_all("a", href=True):
            return "javascript_shell"

        return "tiny_html"

    if "/product/" in low:
        return "catalog_or_product_html"

    return "html_without_product_urls"


def _fetch(session, url, timeout=DISCOVERY_TIMEOUT, debug=True):
    """GET with diagnostics and redirect visibility."""
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        _dbg(
            "http_fetch_error",
            url=url,
            error=f"{type(exc).__name__}: {exc}",
        )
        return None

    if debug:
        soup = BeautifulSoup(response.text or "", "html.parser")
        title = (
            clean(soup.title.get_text(" ", strip=True))
            if soup.title
            else ""
        )
        body_text = clean(soup.get_text(" ", strip=True))

        _dbg(
            "http_response_debug",
            requested_url=url,
            final_url=response.url,
            status=response.status_code,
            bytes=len(response.content or b""),
            content_type=response.headers.get("content-type"),
            kind=_response_kind(response),
            history=[
                {
                    "status": h.status_code,
                    "url": h.url,
                    "location": h.headers.get("location"),
                }
                for h in response.history
            ],
            title=title,
            body_preview=body_text[:500],
            html_preview=(response.text or "")[:1000],
        )

    return response


def availability_from_sources(data, soup):
    """Prefer structured offer availability."""
    offers = data.get("offers") if isinstance(data, dict) else None

    if isinstance(offers, dict):
        offers = [offers]

    if isinstance(offers, list):
        for offer in offers:
            if not isinstance(offer, dict):
                continue

            raw = (
                offer.get("availability")
                or offer.get("availabilityStatus")
                or offer.get("stock")
            )

            if not raw:
                continue

            t = norm(raw)

            if any(
                x in t
                for x in (
                    "instock",
                    "in stock",
                    "available",
                )
            ):
                return "in_stock"

            if any(
                x in t
                for x in (
                    "outofstock",
                    "out of stock",
                    "soldout",
                    "sold out",
                    "unavailable",
                    "not available",
                )
            ):
                return "out_of_stock"

    for tag in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        raw = tag.get("content") or tag.get_text(" ", strip=True)
        t = norm(raw)

        if any(x in t for x in ("instock", "in stock", "available")):
            return "in_stock"

        if any(
            x in t
            for x in (
                "outofstock",
                "out of stock",
                "soldout",
                "sold out",
                "unavailable",
                "not available",
            )
        ):
            return "out_of_stock"

    for node in soup.find_all(
        string=re.compile(
            r"\b(?:in stock|out of stock|sold out|not available|unavailable)\b",
            re.I,
        )
    ):
        t = norm(node)

        if (
            "out of stock" in t
            or "sold out" in t
            or "not available" in t
            or "unavailable" in t
        ):
            return "out_of_stock"

        if "in stock" in t:
            return "in_stock"

    return "unknown"


def _selected_size(soup, data, h1_name):
    """Extract the actually selected bottle size."""
    m = re.search(
        r"(?<!\d)(\d{1,4})\s*ml\b",
        h1_name or "",
        re.I,
    )
    if m:
        return int(m.group(1))

    selectors = [
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        "option[selected]",
        '[aria-selected="true"]',
    ]

    for selector in selectors:
        for node in soup.select(selector):
            chunks = [
                node.get("value", ""),
                node.get("aria-label", ""),
                node.get("data-value", ""),
                node.get("data-size", ""),
                node.get_text(" ", strip=True),
            ]

            parent = node.parent
            if parent:
                chunks.append(parent.get_text(" ", strip=True))

            grand = parent.parent if parent else None
            if grand:
                chunks.append(grand.get_text(" ", strip=True))

            blob = " ".join(chunks)

            m = re.search(
                r"(?<!\d)(\d{1,4})\s*ml\b",
                blob,
                re.I,
            )
            if m:
                return int(m.group(1))

    structured_name = (
        clean(data.get("name"))
        if isinstance(data, dict)
        else ""
    )

    m = re.search(
        r"(?<!\d)(\d{1,4})\s*ml\b",
        structured_name,
        re.I,
    )

    if m:
        return int(m.group(1))

    return None


def _jsonld(soup):
    """Return the first useful Product JSON-LD object."""
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text(strip=True)

        if not raw:
            continue

        try:
            data = json.loads(raw)
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

            item_type = item.get("@type")

            if (
                item_type == "Product"
                or (
                    isinstance(item_type, list)
                    and "Product" in item_type
                )
                or "offers" in item
            ):
                return item

            graph = item.get("@graph")
            if isinstance(graph, list):
                stack.extend(graph)

    return {}


def _product(url, html, query):
    soup = BeautifulSoup(html, "html.parser")
    data = _jsonld(soup)

    h1 = soup.find("h1")
    h1_name = (
        clean(h1.get_text(" ", strip=True))
        if h1
        else ""
    )

    name = h1_name or clean(data.get("name"))

    if not name or not matches(name, query):
        return None

    text = soup.get_text(" ", strip=True)

    product_line = ""
    m = re.search(
        r"product line\s+(.+?)"
        r"(?:for whom|fragrance type|season|spray|article number)",
        text,
        re.I,
    )

    if m:
        product_line = clean(m.group(1))

    brand = data.get("brand")

    if isinstance(brand, dict):
        brand = brand.get("name")

    offers = data.get("offers")

    if isinstance(offers, dict):
        offers = [offers]
    elif not isinstance(offers, list):
        offers = []

    offer = next(
        (x for x in offers if isinstance(x, dict)),
        {},
    )

    price = parse_price(offer.get("price"))

    if price is None:
        price = parse_price(
            offer.get("lowPrice")
            or offer.get("highPrice")
        )

    if price is None:
        price = parse_price(text)

    if price is None:
        return None

    gtin = (
        clean(
            data.get("gtin13")
            or data.get("gtin")
            or ""
        )
        or None
    )

    mpn = clean(data.get("mpn") or "") or None
    sku = clean(data.get("sku") or "") or None

    image = data.get("image")

    if isinstance(image, list):
        image = image[0] if image else None

    avail = availability_from_sources(data, soup)
    selected_size = _selected_size(
        soup,
        data,
        h1_name,
    )

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": clean(brand),
            "url": url,
            "image": (
                urljoin(url, str(image))
                if image
                else None
            ),
        },
        "identity": {
            "gtin": (
                {
                    "value": gtin,
                    "source": "jsonld",
                }
                if gtin
                else None
            ),
            "mpn": (
                {
                    "value": mpn,
                    "source": "jsonld",
                }
                if mpn
                else None
            ),
            "sku": (
                {
                    "value": sku,
                    "source": "jsonld",
                }
                if sku
                else None
            ),
            "store_product_id": (
                {
                    "value": sku,
                    "source": "deloox_sku",
                }
                if sku
                else None
            ),
        },
        "attributes": {
            "size_ml": (
                {
                    "value": selected_size,
                    "source": "selected_variant_or_product_name",
                }
                if selected_size is not None
                else None
            ),
            "concentration": (
                {
                    "value": concentration(name),
                    "source": "product_name",
                }
                if concentration(name)
                else None
            ),
            "gender": {
                "value": "unknown",
                "source": "not_explicit",
            },
            "packaging_type": {
                "value": "product",
                "source": "default",
            },
            "product_line": (
                {
                    "value": product_line,
                    "source": "deloox_page",
                }
                if product_line
                else None
            ),
        },
        "offer": {
            "price": price,
            "currency": "EUR",
            "availability": avail,
        },
        "provenance": {
            "source_page": url,
            "product_source": "jsonld_or_page",
        },
        "raw_data": {
            "jsonld": data,
        },
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": avail == "in_stock",
    }


def _inspect_category_structure(
    html,
    query,
    url,
    max_query_hits=5,
    max_product_hits=5,
    max_category_hits=5,
):
    """Diagnostic only."""
    raw = html or ""
    low = raw.lower()
    q = clean(query)

    def snippets(term, limit):
        if not term:
            return []

        term_low = term.lower()
        out = []
        start = 0

        while len(out) < limit:
            pos = low.find(term_low, start)

            if pos < 0:
                break

            left = max(0, pos - 220)
            right = min(
                len(raw),
                pos + len(term) + 420,
            )

            out.append(
                {
                    "offset": pos,
                    "snippet": clean(raw[left:right]),
                }
            )

            start = pos + max(1, len(term))

        return out

    structural_terms = (
        "__next_data__",
        "__nuxt__",
        "application/ld+json",
        "productName",
        "product_name",
        "productTitle",
        "category",
        "product line",
        "productline",
        "collection",
        "breadcrumbs",
        "itemListElement",
        "data-product",
        "data-category",
        "apollo",
        "graphql",
        "__next",
        "nuxt",
    )

    markers = {
        term: low.count(term.lower())
        for term in structural_terms
        if term.lower() in low
    }

    _dbg(
        "category_structure",
        query=q,
        url=url,
        bytes=len(raw),
        html_category_count=low.count("/category/"),
        html_product_count=low.count("/product/"),
        query_count=(
            low.count(norm(q))
            if norm(q)
            else 0
        ),
        structural_markers=markers,
        query_snippets=snippets(
            q,
            max_query_hits,
        ),
        product_snippets=snippets(
            "/product/",
            max_product_hits,
        ),
        category_snippets=snippets(
            "/category/",
            max_category_hits,
        ),
    )


def _candidate_product_urls(html, query=None):
    """Extract only product URLs with a LOCAL match to the query."""
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    q_tokens = tokens(query or "")

    if not q_tokens:
        return []

    def add(raw_url, context=""):
        if not raw_url:
            return

        raw_url = clean(raw_url).replace(
            "\\/",
            "/",
        )

        if raw_url.startswith(
            (
                "javascript:",
                "mailto:",
                "#",
            )
        ):
            return

        url = (
            urljoin(BASE_URL, raw_url)
            .split("#")[0]
            .split("?")[0]
        )

        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            return

        if "/product/" not in parsed.path.lower():
            return

        if url in seen:
            return

        # The query must be supported by the local card/name OR the slug.
        if not matches(
            f"{context} {url}",
            query,
        ):
            return

        seen.add(url)
        found.append(url)

    # Normal visible anchors.
    for a in soup.find_all(
        "a",
        href=True,
    ):
        href = clean(a.get("href", ""))

        if "/product/" not in href.lower():
            continue

        context_parts = [
            a.get_text(" ", strip=True),
            a.get("aria-label", ""),
            a.get("title", ""),
            a.get("data-name", ""),
            a.get("data-product-name", ""),
            a.get("data-testid", ""),
        ]

        context = " ".join(
            clean(x)
            for x in context_parts
            if clean(x)
        )

        if not context and a.parent:
            context = a.parent.get_text(
                " ",
                strip=True,
            )

        add(href, context)

    raw = html.replace(
        "\\\\/",
        "/",
    )

    patterns = (
        r'https?://(?:www\.)?deloox\.com'
        r'[^"\'<>\s]*/product/[^"\'<>\s]+',

        r'(?<![A-Za-z0-9])'
        r'(?:/|(?:en|it|nl)/)'
        r'product/[^"\'<>\s]+',
    )

    def local_product_context(
        blob,
        start,
        end,
    ):
        """Find the nearest useful JSON/JS product name."""
        # Search several possible object starts. A single nearest "{" can
        # belong to an unrelated nested object.
        search_from = start

        for _ in range(8):
            obj_left = blob.rfind(
                "{",
                0,
                search_from,
            )

            if obj_left < 0:
                break

            obj_right = blob.find(
                "}",
                end,
            )

            if (
                obj_right >= end
                and obj_right - obj_left <= 6000
            ):
                object_text = blob[
                    obj_left:obj_right + 1
                ]

                name_patterns = (
                    r'"(?:name|productName|product_name|title|productTitle)"'
                    r'\s*:\s*"([^"]{1,300})"',

                    r"'(?:name|productName|product_name|title|productTitle)'"
                    r"\s*:\s*'([^']{1,300})'",

                    r'\b(?:name|productName|product_name|title|productTitle)'
                    r'\s*:\s*"([^"]{1,300})"',

                    r"\b(?:name|productName|product_name|title|productTitle)"
                    r"\s*:\s*'([^']{1,300})'",
                )

                for pattern in name_patterns:
                    match = re.search(
                        pattern,
                        object_text,
                        re.I,
                    )
                    if match:
                        return match.group(1)

            search_from = obj_left

        return ""

    # Scan serialized scripts and likely product cards.
    for tag in soup.find_all(
        ["script", "div", "article", "li"]
    ):
        if tag.name == "script":
            blob = tag.get_text()
        else:
            blob = tag.get_text(
                " ",
                strip=True,
            )

        if "/product/" not in blob.lower():
            continue

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                blob,
                re.I,
            ):
                context = local_product_context(
                    blob,
                    match.start(),
                    match.end(),
                )

                add(
                    match.group(0),
                    context,
                )

    # Final raw HTML pass.
    for pattern in patterns:
        for match in re.finditer(
            pattern,
            raw,
            re.I,
        ):
            context = local_product_context(
                raw,
                match.start(),
                match.end(),
            )

            add(
                match.group(0),
                context,
            )

    return found[:80]


def _category_product_line_links(html, query):
    """Find category URLs matching all query tokens."""
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    q_tokens = tokens(query)

    if not q_tokens:
        return []

    def add(raw_url, label=""):
        raw_url = clean(raw_url).replace(
            "\\/",
            "/",
        )

        if not raw_url:
            return

        url = (
            urljoin(BASE_URL, raw_url)
            .split("#")[0]
            .split("?")[0]
        )

        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            return

        if "/category/" not in parsed.path.lower():
            return

        slug_text = parsed.path.rsplit(
            "/",
            1,
        )[-1]

        if slug_text.lower().endswith(".html"):
            slug_text = slug_text[:-5]

        if not (
            q_tokens.issubset(tokens(slug_text))
            or q_tokens.issubset(tokens(label))
        ):
            return

        if url in seen:
            return

        seen.add(url)
        links.append(url)

    # Visible anchors.
    for a in soup.find_all(
        "a",
        href=True,
    ):
        add(
            a.get("href"),
            a.get_text(
                " ",
                strip=True,
            ),
        )

    # Serialized URLs.
    raw = html.replace(
        "\\\\/",
        "/",
    )

    pattern = (
        r'(?:(?:https?:)?//(?:www\.)?deloox\.com)?'
        r'/(?:en/|it/|nl/)?'
        r'category/\d+/[^"\'<>\s]+\.html'
    )

    for match in re.findall(
        pattern,
        raw,
        re.I,
    ):
        add(match)

    return links


def _catalog_filter_links(session):
    """Discover category links from the live catalogue."""
    global CATALOG_FILTER_LINKS

    if CATALOG_FILTER_LINKS is not None:
        return CATALOG_FILTER_LINKS

    response = _fetch(
        session,
        CATALOG_URL,
        timeout=TIMEOUT,
    )

    if response is None or response.status_code >= 400:
        return []

    html = response.text or ""

    if len(response.content or b"") < MIN_REAL_CATEGORY_BYTES:
        _dbg(
            "catalog_suspicious_response",
            url=CATALOG_URL,
            bytes=len(response.content or b""),
            kind=_response_kind(response),
        )
        return []

    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    links = []
    seen = set()

    def add(raw_url, label=""):
        raw_url = clean(raw_url).replace(
            "\\/",
            "/",
        )

        if not raw_url:
            return

        url = (
            urljoin(BASE_URL, raw_url)
            .split("#")[0]
        )

        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            return

        if "/category/" not in parsed.path.lower():
            return

        if url in seen:
            return

        seen.add(url)
        links.append(
            (
                clean(label),
                url,
            )
        )

    for a in soup.find_all(
        "a",
        href=True,
    ):
        href = clean(a.get("href", ""))

        if "/category/" in href.lower():
            add(
                href,
                a.get_text(
                    " ",
                    strip=True,
                ),
            )

    raw = html.replace(
        "\\\\/",
        "/",
    )

    patterns = (
        r'https?://(?:www\.)?deloox\.com'
        r'(?:/en)?/category/\d+/[^"\'<>\s]+\.html',

        r'["\']((?:https?:)?//(?:www\.)?deloox\.com'
        r'(?:/en)?/category/\d+/[^"\'<>\s]+\.html)["\']',

        r'["\']((?:/)?(?:en/)?category/\d+/'
        r'[^"\'<>\s]+\.html)["\']',
    )

    for pattern in patterns:
        for raw_url in re.findall(
            pattern,
            raw,
            re.I,
        ):
            if isinstance(raw_url, tuple):
                raw_url = "".join(raw_url)

            add(raw_url)

    CATALOG_FILTER_LINKS = links
    return CATALOG_FILTER_LINKS


def _find_catalog_filter_url(session, query):
    """Find the strongest catalogue category matching the query."""
    q_tokens = tokens(query)

    if not q_tokens:
        return None

    candidates = []

    for label, url in _catalog_filter_links(session):
        path_name = urlparse(url).path.rsplit(
            "/",
            1,
        )[-1]

        if path_name.lower().endswith(".html"):
            path_name = path_name[:-5]

        label_tokens = set(tokens(label))
        slug_tokens = set(tokens(path_name))

        label_hits = len(
            q_tokens & label_tokens
        )
        slug_hits = len(
            q_tokens & slug_tokens
        )

        hits = max(
            label_hits,
            slug_hits,
        )

        if hits == 0:
            continue

        score = hits * 100

        if q_tokens.issubset(label_tokens):
            score += 1000

        if q_tokens.issubset(slug_tokens):
            score += 900

        score += min(
            label_hits,
            slug_hits,
        ) * 10

        candidates.append(
            (
                score,
                label,
                url,
            )
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            -item[0],
            len(item[1]),
            item[2],
        )
    )

    return candidates[0][2]


def _category_pages(session=None):
    """Generic Deloox catalogue roots.

    Keep the locale consistent. The old adapter mixed /category/ and /en/.
    """
    return (
        BASE_URL + "/en/category/1000003/fragrances.html",
        BASE_URL + "/en/category/1075639/womens-fragrances.html",
        BASE_URL + "/en/category/1075660/womens-perfume.html",
        BASE_URL + "/en/category/1000054/mens-fragrances.html",
        BASE_URL + "/en/category/1025540/trending.html",
    )


def _sitemap_category_urls(
    session,
    query,
    max_sitemaps=16,
    max_urls=50,
):
    q_tokens = tokens(query)

    if not q_tokens:
        return []

    roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(roots)
    seen_sitemaps = set()
    found = []
    seen_urls = set()

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(found) < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(sitemap_url)

        response = _fetch(
            session,
            sitemap_url,
            timeout=DISCOVERY_TIMEOUT,
        )

        if response is None or response.status_code >= 400:
            continue

        body = (response.text or "").lstrip()

        if not body.startswith(
            (
                "<?xml",
                "<urlset",
                "<sitemapindex",
            )
        ):
            continue

        soup = BeautifulSoup(
            response.text,
            "xml",
        )

        for loc in soup.find_all("loc"):
            value = clean(
                loc.get_text()
            )

            if not value:
                continue

            low = value.lower()

            if (
                low.endswith(".xml")
                or "sitemap" in low
            ):
                if (
                    value not in seen_sitemaps
                    and value not in pending
                ):
                    pending.append(value)
                continue

            parsed = urlparse(value)

            if parsed.netloc.lower() not in {
                "deloox.com",
                "www.deloox.com",
            }:
                continue

            path = parsed.path.lower()

            if (
                "/category/" not in path
                or not path.endswith(".html")
            ):
                continue

            slug = path.rsplit(
                "/",
                1,
            )[-1][:-5]

            if not q_tokens.issubset(
                tokens(slug)
            ):
                continue

            clean_url = (
                value
                .split("#")[0]
                .split("?")[0]
            )

            if clean_url not in seen_urls:
                seen_urls.add(clean_url)
                found.append(clean_url)

                if len(found) >= max_urls:
                    break

    return found


def _pagination_urls(page_url, max_pages=8):
    base = page_url.split("?")[0]

    for page in range(
        1,
        max_pages + 1,
    ):
        yield (
            f"{base}?page={page}"
        )


def _explicit_next_url(html, current_url):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    # Standard rel=next.
    link = soup.find(
        "link",
        attrs={
            "rel": lambda value:
                value
                and "next"
                in str(value).lower()
        },
    )

    if link and link.get("href"):
        return (
            urljoin(
                current_url,
                clean(link.get("href")),
            )
            .split("#")[0]
        )

    # Some sites expose next as an anchor.
    for a in soup.find_all(
        "a",
        href=True,
    ):
        rel = " ".join(
            a.get("rel", [])
        ).lower()

        aria = clean(
            a.get("aria-label", "")
        ).lower()

        text = clean(
            a.get_text(
                " ",
                strip=True,
            )
        ).lower()

        if (
            "next" in rel
            or "next page" in aria
            or text in {"next", "next page", ">"}
        ):
            return (
                urljoin(
                    current_url,
                    clean(a.get("href")),
                )
                .split("#")[0]
            )

    return None


def _discover_from_categories(
    session,
    query,
    max_urls=80,
):
    """Discover products through catalogue pages.

    Crucially, do not paginate through a tiny HTML shell. The screenshots show
    Deloox returning ~1.5 KB with HTTP 200; treating that as a real catalogue
    causes the adapter to waste dozens of requests.
    """
    urls = []
    seen = set()
    visited = set()

    max_root_pages = 12

    def add_products(html, source):
        candidates = _candidate_product_urls(
            html,
            query,
        )

        _dbg(
            "candidate_scan",
            query=query,
            source=source,
            count=len(candidates),
            sample=candidates[:10],
        )

        for product_url in candidates:
            if product_url in seen:
                continue

            seen.add(product_url)
            urls.append(product_url)

            if len(urls) >= max_urls:
                return True

        return False

    roots = list(
        _category_pages(session)
    )

    _dbg(
        "category_roots",
        query=query,
        roots=roots,
    )

    for root_index, root in enumerate(roots):
        page_url = root

        # The first three roots are the main fragrance roots. The remaining
        # roots are only secondary fallbacks.
        root_page_limit = (
            max_root_pages
            if root_index < 3
            else 3
        )

        for page_index in range(
            root_page_limit
        ):
            if page_url in visited:
                break

            visited.add(page_url)

            response = _fetch(
                session,
                page_url,
                timeout=DISCOVERY_TIMEOUT,
            )

            if response is None:
                break

            _dbg(
                "category_fetch",
                query=query,
                url=page_url,
                final_url=response.url,
                status=response.status_code,
                bytes=len(response.content or b""),
                page=page_index + 1,
                kind=_response_kind(response),
            )

            if response.status_code >= 400:
                break

            # This is the important fix for the Railway logs:
            # 1531/1535-byte responses are not real catalogue pages.
            if (
                len(response.content or b"")
                < MIN_REAL_CATEGORY_BYTES
            ):
                _dbg(
                    "category_suspicious_response",
                    query=query,
                    url=page_url,
                    final_url=response.url,
                    status=response.status_code,
                    bytes=len(response.content or b""),
                    kind=_response_kind(response),
                )
                break

            html = response.text or ""

            if (
                root_index == 0
                and page_index == 0
            ):
                _inspect_category_structure(
                    html,
                    query,
                    page_url,
                )

            if add_products(
                html,
                page_url,
            ):
                return urls[:max_urls]

            matching_lines = (
                _category_product_line_links(
                    html,
                    query,
                )
            )

            _dbg(
                "matching_category_links",
                query=query,
                source=page_url,
                count=len(matching_lines),
                links=matching_lines[:20],
            )

            # Follow matching product-line/category filters.
            for line_url in matching_lines[:8]:
                category_pages = [
                    line_url,
                    next(
                        _pagination_urls(
                            line_url,
                            max_pages=1,
                        )
                    ),
                ]

                for category_page_url in category_pages:
                    if (
                        category_page_url
                        in visited
                    ):
                        continue

                    visited.add(
                        category_page_url
                    )

                    page = _fetch(
                        session,
                        category_page_url,
                        timeout=DISCOVERY_TIMEOUT,
                    )

                    if page is None:
                        continue

                    _dbg(
                        "category_link_fetch",
                        query=query,
                        url=category_page_url,
                        final_url=page.url,
                        status=page.status_code,
                        bytes=len(page.content or b""),
                        kind=_response_kind(page),
                    )

                    if page.status_code >= 400:
                        continue

                    if (
                        len(page.content or b"")
                        < MIN_REAL_CATEGORY_BYTES
                    ):
                        _dbg(
                            "category_link_suspicious_response",
                            query=query,
                            url=category_page_url,
                            bytes=len(page.content or b""),
                            kind=_response_kind(page),
                        )
                        continue

                    if add_products(
                        page.text or "",
                        category_page_url,
                    ):
                        return urls[:max_urls]

            next_url = _explicit_next_url(
                html,
                page_url,
            )

            if not next_url:
                # Use bounded numeric pagination only when the current page
                # is demonstrably a real catalogue page.
                next_page_number = page_index + 2

                next_url = (
                    f"{root}?page={next_page_number}"
                )

            if (
                not next_url
                or next_url == page_url
            ):
                break

            page_url = next_url

    _dbg(
        "category_discovery_done",
        query=query,
        count=len(urls),
        urls=urls[:20],
    )

    return urls[:max_urls]


def _sitemap_product_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=80,
):
    query_tokens = tokens(query)

    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(
        sitemap_roots
    )
    seen_sitemaps = set()
    product_urls = []
    seen_products = set()

    while (
        pending
        and len(seen_sitemaps)
        < max_sitemaps
        and len(product_urls)
        < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(
            sitemap_url
        )

        response = _fetch(
            session,
            sitemap_url,
            timeout=DISCOVERY_TIMEOUT,
        )

        if (
            response is None
            or response.status_code >= 400
        ):
            continue

        body = (
            response.text or ""
        ).lstrip()

        if not body.startswith(
            (
                "<?xml",
                "<urlset",
                "<sitemapindex",
            )
        ):
            continue

        soup = BeautifulSoup(
            response.text,
            "xml",
        )

        for loc in soup.find_all("loc"):
            value = clean(
                loc.get_text()
            )

            if not value:
                continue

            low = value.lower()

            if "/product/" in low:
                if query_tokens.issubset(
                    tokens(value)
                ):
                    clean_value = (
                        value
                        .split("#")[0]
                        .split("?")[0]
                    )

                    if clean_value not in seen_products:
                        seen_products.add(
                            clean_value
                        )
                        product_urls.append(
                            clean_value
                        )

                        if (
                            len(product_urls)
                            >= max_urls
                        ):
                            break

            elif (
                low.endswith(".xml")
                or "sitemap" in low
            ):
                if (
                    value
                    not in seen_sitemaps
                    and value
                    not in pending
                ):
                    pending.append(value)

    return product_urls


def _discover(session, q):
    """Generic Deloox discovery."""
    urls = []
    seen = set()

    def add_many(items, source):
        items = list(items or [])

        _dbg(
            "discovery_candidates",
            query=q,
            source=source,
            count=len(items),
            sample=items[:20],
        )

        for url in items:
            if url in seen:
                continue

            seen.add(url)
            urls.append(url)

            if len(urls) >= 80:
                return True

        return False

    # 1. Category discovery.
    category_candidates = (
        _discover_from_categories(
            session,
            q,
            max_urls=80,
        )
    )

    if category_candidates:
        _dbg(
            "discovery_stop",
            query=q,
            source="categories",
            count=len(category_candidates),
        )
        add_many(
            category_candidates,
            "categories",
        )
        return urls[:80]

    # 2. Catalogue filter discovery.
    catalog_category = (
        _find_catalog_filter_url(
            session,
            q,
        )
    )

    _dbg(
        "catalog_match",
        query=q,
        url=catalog_category,
    )

    if catalog_category:
        page = _fetch(
            session,
            catalog_category,
            timeout=DISCOVERY_TIMEOUT,
        )

        if (
            page is not None
            and page.status_code < 400
            and len(page.content or b"")
            >= MIN_REAL_CATEGORY_BYTES
        ):
            candidates = (
                _candidate_product_urls(
                    page.text or "",
                    q,
                )
            )

            _dbg(
                "catalog_candidates",
                query=q,
                count=len(candidates),
                sample=candidates[:20],
            )

            if add_many(
                candidates,
                "catalog",
            ):
                return urls[:80]

    # 3. Category sitemap discovery.
    sitemap_categories = (
        _sitemap_category_urls(
            session,
            q,
            max_sitemaps=6,
            max_urls=12,
        )
    )

    _dbg(
        "sitemap_category_matches",
        query=q,
        count=len(sitemap_categories),
        urls=sitemap_categories[:20],
    )

    for category_url in sitemap_categories:
        page = _fetch(
            session,
            category_url,
            timeout=DISCOVERY_TIMEOUT,
        )

        if (
            page is None
            or page.status_code >= 400
        ):
            continue

        if (
            len(page.content or b"")
            < MIN_REAL_CATEGORY_BYTES
        ):
            _dbg(
                "sitemap_category_suspicious_response",
                query=q,
                url=category_url,
                bytes=len(page.content or b""),
                kind=_response_kind(page),
            )
            continue

        candidates = (
            _candidate_product_urls(
                page.text or "",
                q,
            )
        )

        if add_many(
            candidates,
            "sitemap_category",
        ):
            return urls[:80]

    # 4. Search endpoints.
    endpoints = (
        BASE_URL
        + "/en/search?q="
        + quote_plus(q),

        BASE_URL
        + "/en/search?query="
        + quote_plus(q),

        BASE_URL
        + "/search?q="
        + quote_plus(q),
    )

    for endpoint in endpoints:
        response = _fetch(
            session,
            endpoint,
            timeout=DISCOVERY_TIMEOUT,
        )

        if (
            response is None
            or response.status_code >= 400
        ):
            continue

        if (
            len(response.content or b"")
            < MIN_REAL_CATEGORY_BYTES
        ):
            _dbg(
                "search_suspicious_response",
                query=q,
                url=endpoint,
                bytes=len(response.content or b""),
                kind=_response_kind(response),
            )
            continue

        candidates = (
            _candidate_product_urls(
                response.text or "",
                q,
            )
        )

        if add_many(
            candidates,
            "search",
        ):
            return urls[:80]

    # 5. Product sitemap fallback.
    sitemap_candidates = (
        _sitemap_product_urls(
            session,
            q,
            max_sitemaps=6,
            max_urls=40,
        )
    )

    _dbg(
        "product_sitemap_candidates",
        query=q,
        count=len(sitemap_candidates),
        sample=sitemap_candidates[:20],
    )

    add_many(
        sitemap_candidates,
        "product_sitemap",
    )

    _dbg(
        "discovery_done",
        query=q,
        count=len(urls),
        urls=urls[:20],
    )

    return urls[:80]


def _product_rejection_reason(
    url,
    html,
    query,
):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    data = _jsonld(soup)

    h1 = soup.find("h1")
    h1_name = (
        clean(
            h1.get_text(
                " ",
                strip=True,
            )
        )
        if h1
        else ""
    )

    name = (
        h1_name
        or clean(data.get("name"))
    )

    if not name:
        return "missing_product_name"

    if not matches(
        name,
        query,
    ):
        return (
            "name_mismatch: "
            + name
        )

    offers = data.get("offers")

    if isinstance(offers, dict):
        offers = [offers]
    elif not isinstance(offers, list):
        offers = []

    offer = next(
        (
            x
            for x in offers
            if isinstance(x, dict)
        ),
        {},
    )

    price = parse_price(
        offer.get("price")
    )

    if price is None:
        price = parse_price(
            BeautifulSoup(
                html,
                "html.parser",
            ).get_text(
                " ",
                strip=True,
            )
        )

    if price is None:
        return "missing_price"

    return None


def diagnostic_discovery(query):
    """Detailed diagnostic without running the complete product search."""
    session = requests.Session()
    out = {
        "query": clean(query),
        "stages": [],
    }

    try:
        catalog_t0 = time.monotonic()

        try:
            catalog_links = (
                _catalog_filter_links(
                    session
                )
            )
            catalog_error = None
        except Exception as exc:
            catalog_links = []
            catalog_error = (
                f"{type(exc).__name__}: {exc}"
            )

        out["catalog_discovery"] = {
            "url": CATALOG_URL,
            "seconds": round(
                time.monotonic()
                - catalog_t0,
                3,
            ),
            "link_count": len(
                catalog_links
            ),
            "matching_url": (
                _find_catalog_filter_url(
                    session,
                    query,
                )
                if not catalog_error
                else None
            ),
            "error": catalog_error,
        }

        roots = list(
            _category_pages(session)
        )

        out["category_roots"] = roots

        for root in roots:
            t0 = time.monotonic()

            response = _fetch(
                session,
                root,
                timeout=DISCOVERY_TIMEOUT,
            )

            if response is None:
                out["stages"].append(
                    {
                        "stage": "category",
                        "url": root,
                        "error": "request_failed",
                    }
                )
                continue

            elapsed = round(
                time.monotonic()
                - t0,
                3,
            )

            out["stages"].append(
                {
                    "stage": "category",
                    "url": root,
                    "final_url": response.url,
                    "status": response.status_code,
                    "seconds": elapsed,
                    "bytes": len(
                        response.content or b""
                    ),
                    "kind": _response_kind(
                        response
                    ),
                }
            )

            if response.status_code >= 400:
                continue

            if (
                len(response.content or b"")
                < MIN_REAL_CATEGORY_BYTES
            ):
                out["stages"].append(
                    {
                        "stage": "category_shell",
                        "url": root,
                        "bytes": len(
                            response.content or b""
                        ),
                        "kind": _response_kind(
                            response
                        ),
                    }
                )
                continue

            links = (
                _category_product_line_links(
                    response.text or "",
                    query,
                )
            )

            out["stages"].append(
                {
                    "stage": "product_line_links",
                    "source": root,
                    "count": len(links),
                    "links": links[:10],
                }
            )

            for link in links[:3]:
                t1 = time.monotonic()

                page = _fetch(
                    session,
                    link,
                    timeout=DISCOVERY_TIMEOUT,
                )

                if page is None:
                    out["stages"].append(
                        {
                            "stage": "product_line_page",
                            "url": link,
                            "error": "request_failed",
                        }
                    )
                    continue

                elapsed = round(
                    time.monotonic()
                    - t1,
                    3,
                )

                urls = (
                    _candidate_product_urls(
                        page.text or "",
                        query,
                    )
                    if (
                        page.status_code < 400
                        and len(
                            page.content or b""
                        )
                        >= MIN_REAL_CATEGORY_BYTES
                    )
                    else []
                )

                out["stages"].append(
                    {
                        "stage": "product_line_page",
                        "url": link,
                        "final_url": page.url,
                        "status": page.status_code,
                        "seconds": elapsed,
                        "bytes": len(
                            page.content or b""
                        ),
                        "kind": _response_kind(
                            page
                        ),
                        "product_urls": len(urls),
                        "sample": urls[:5],
                    }
                )

        return out

    finally:
        session.close()


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()

    try:
        discovered = _discover(
            session,
            query,
        )

        _dbg(
            "search_discovered",
            query=query,
            count=len(discovered),
            urls=discovered[:50],
        )

        for url in discovered:
            response = _fetch(
                session,
                url,
                timeout=TIMEOUT,
            )

            if response is None:
                continue

            _dbg(
                "product_fetch",
                query=query,
                url=url,
                final_url=response.url,
                status=response.status_code,
                bytes=len(
                    response.content or b""
                ),
                kind=_response_kind(
                    response
                ),
            )

            if response.status_code >= 400:
                _dbg(
                    "product_rejected",
                    query=query,
                    url=url,
                    reason=(
                        f"http_{response.status_code}"
                    ),
                )
                continue

            item = _product(
                url,
                response.text or "",
                query,
            )

            if not item:
                reason = (
                    _product_rejection_reason(
                        url,
                        response.text or "",
                        query,
                    )
                )

                _dbg(
                    "product_rejected",
                    query=query,
                    url=url,
                    reason=(
                        reason
                        or "unknown"
                    ),
                )

                continue

            sku_value = None
            sku = item["identity"].get(
                "sku"
            )

            if sku:
                sku_value = sku.get(
                    "value"
                )

            key = (
                url,
                sku_value,
            )

            if key in seen:
                _dbg(
                    "product_duplicate",
                    query=query,
                    url=url,
                    sku=sku_value,
                )
                continue

            seen.add(key)
            results.append(item)

            _dbg(
                "product_accepted",
                query=query,
                url=url,
                name=item.get("name"),
                sku=sku_value,
                price=item.get("price"),
            )

        _dbg(
            "search_done",
            query=query,
            result_count=len(results),
        )

        return results

    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Deloox adapter for ScentHunter"
    )

    parser.add_argument(
        "query"
    )

    parser.add_argument(
        "--diagnose",
        action="store_true",
    )

    args = parser.parse_args()

    payload = (
        diagnostic_discovery(args.query)
        if args.diagnose
        else search(args.query)
    )

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        )
    )
