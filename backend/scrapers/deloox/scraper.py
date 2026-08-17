"""Deloox adapter for ScentHunter.

Discovery strategy:
1. Resolve a dedicated Deloox Product Line/category for the query.
2. Try Deloox search pages for category/product links.
3. Try Deloox category sitemaps.
4. Use the broad fragrance categories only as a fallback.
5. Parse product pages through JSON-LD/page content.

Important:
- No product-specific IDs or product-specific URLs are hard-coded.
- The adapter does NOT assume that a broad fragrance category contains the
  requested product.
- A category is considered relevant only when its slug/label/local context
  actually matches the query.
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
DISCOVERY_TIMEOUT = 5
DEBUG_DISCOVERY = os.getenv("DELOOX_DEBUG", "1") != "0"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}

# This is only a generic catalogue entry point. It is NOT a product seed.
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
    return {
        x
        for x in norm(v).split()
        if len(x) > 1
    }


def query_tokens(v):
    """Return normalized query tokens for discovery scoring."""
    return tokens(v)


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
    n *= 10 if m.group(2).lower() == "cl" else 1
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

    # Accept both:
    #   49.95
    #   49,95
    #   €49.95
    #   49.95 €
    m = re.search(
        r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?",
        s,
    )

    if not m:
        return None

    try:
        return round(
            float(m.group(1).replace(",", ".")),
            2,
        )
    except ValueError:
        return None


def availability_from_sources(data, soup):
    """Prefer structured offer availability.

    Never classify availability from arbitrary page text unless the text node
    itself is an explicit stock message.
    """
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

            if raw:
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

    # Secondary source: explicit HTML metadata only.
    for tag in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        raw = tag.get("content") or tag.get_text(
            " ",
            strip=True,
        )

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

    # Last resort: inspect only explicit stock-message nodes.
    for node in soup.find_all(
        string=re.compile(
            r"\b(?:in stock|out of stock|sold out|"
            r"not available|unavailable)\b",
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
                chunks.append(
                    parent.get_text(" ", strip=True)
                )

            grand = parent.parent if parent else None
            if grand:
                chunks.append(
                    grand.get_text(" ", strip=True)
                )

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
    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        try:
            data = json.loads(
                script.get_text(strip=True)
            )
        except Exception:
            continue

        stack = (
            data
            if isinstance(data, list)
            else [data]
        )

        while stack:
            x = stack.pop(0)

            if isinstance(x, list):
                stack.extend(x)
                continue

            if not isinstance(x, dict):
                continue

            x_type = x.get("@type")

            if (
                x_type == "Product"
                or (
                    isinstance(x_type, list)
                    and "Product" in x_type
                )
                or "offers" in x
            ):
                return x

            if isinstance(x.get("@graph"), list):
                stack.extend(x["@graph"])

    return {}


def _product(url, html, query):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    data = _jsonld(soup)

    h1 = soup.find("h1")
    h1_name = (
        clean(h1.get_text(" ", strip=True))
        if h1
        else ""
    )

    # H1 is preferred because Deloox JSON-LD can contain a stale/SEO variant.
    name = h1_name or clean(data.get("name"))

    if not name or not matches(name, query):
        return None

    product_line = ""
    text = soup.get_text(
        " ",
        strip=True,
    )

    m = re.search(
        r"product line\s+(.+?)(?:for whom|fragrance type|season|spray|article number)",
        text,
        re.I,
    )

    if m:
        product_line = clean(m.group(1))

    brand = data.get("brand")

    if isinstance(brand, dict):
        brand = brand.get("name")

    offers = data.get("offers")
    offers = (
        offers
        if isinstance(offers, list)
        else [offers]
    )

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
        price = parse_price(text)

    if price is None:
        return None

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin")
        or ""
    ) or None

    mpn = clean(
        data.get("mpn") or ""
    ) or None

    sku = clean(
        data.get("sku") or ""
    ) or None

    image = data.get("image")

    if isinstance(image, list):
        image = (
            image[0]
            if image
            else None
        )

    avail = availability_from_sources(
        data,
        soup,
    )

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
                urljoin(
                    url,
                    str(image),
                )
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
    max_query_hits=8,
    max_product_hits=8,
    max_category_hits=8,
):
    """Diagnostic only.

    It reports structural markers and local snippets from the live HTML.
    It does not select product candidates.
    """
    raw = html or ""
    low = raw.lower()
    q = clean(query)

    def snippets(term, limit):
        term_low = term.lower()
        out = []
        start = 0

        while len(out) < limit:
            pos = low.find(
                term_low,
                start,
            )

            if pos < 0:
                break

            left = max(
                0,
                pos - 220,
            )

            right = min(
                len(raw),
                pos + len(term) + 420,
            )

            snippet = clean(
                raw[left:right]
            )

            out.append(
                {
                    "offset": pos,
                    "snippet": snippet,
                }
            )

            start = pos + max(
                1,
                len(term),
            )

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
        query_snippets=(
            snippets(q, max_query_hits)
            if q
            else []
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


def _product_url_context(blob, start, end):
    """Return the nearest product-name field for one URL.

    The important rule is that we never use the whole page as context.
    """
    obj_left = blob.rfind(
        "{",
        0,
        start,
    )

    obj_right = blob.find(
        "}",
        end,
    )

    if (
        obj_left >= 0
        and obj_right >= end
        and (obj_right - obj_left) <= 5000
    ):
        object_text = blob[
            obj_left : obj_right + 1
        ]

        name_patterns = (
            r'"(?:name|productName|product_name|title|productTitle)"\s*:\s*"([^"]{1,400})"',
            r"'(?:name|productName|product_name|title|productTitle)'\s*:\s*'([^']{1,400})'",
            r'\b(?:name|productName|product_name|title|productTitle)\s*:\s*"([^"]{1,400})"',
            r"\b(?:name|productName|product_name|title|productTitle)\s*:\s*'([^']{1,400})'",
        )

        for pattern in name_patterns:
            nm = re.search(
                pattern,
                object_text,
                re.I,
            )

            if nm:
                return clean(
                    nm.group(1)
                )

    return ""


def _product_urls_by_slug(html, query):
    """Find Deloox product URLs whose own slug contains the full query.

    This is intentionally independent of page-level text. It is a fallback for
    Deloox templates where product names and hrefs are serialized separately.
    """
    q_tokens = tokens(query)

    if not q_tokens:
        return []

    raw = (
        html or ""
    ).replace(
        "\\\\/",
        "/",
    ).replace(
        "\\/",
        "/",
    )

    soup = BeautifulSoup(
        raw,
        "html.parser",
    )

    found = []
    seen = set()

    def add(raw_url):
        if not raw_url:
            return

        raw_url = clean(raw_url)

        if raw_url.startswith(
            (
                "javascript:",
                "mailto:",
                "#",
            )
        ):
            return

        url = (
            urljoin(
                BASE_URL,
                raw_url,
            )
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

        if not q_tokens.issubset(
            tokens(parsed.path)
        ):
            return

        seen.add(url)
        found.append(url)

    for a in soup.find_all(
        "a",
        href=True,
    ):
        href = clean(
            a.get("href", "")
        )

        if "/product/" in href.lower():
            add(href)

    patterns = (
        r'https?://(?:www\.)?deloox\.com[^"\'<>\s]*/product/[^"\'<>\s]+',
        r'(?<![A-Za-z0-9])(?:/|(?:en|it|nl)/)product/[^"\'<>\s]+',
    )

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            raw,
            re.I,
        ):
            add(match.group(0))

    return found[:80]


def _product_card_context(anchor, query):
    """Find query-relevant text in the nearest product-card ancestors.

    The link can sit on the product image while the product name lives in a
    sibling element. We inspect only a small ancestor window, never the whole
    page.
    """
    node = anchor
    fallback = ""

    for _ in range(6):
        node = node.parent if node is not None else None

        if node is None:
            break

        context = clean(
            node.get_text(
                " ",
                strip=True,
            )
        )

        if not context or len(context) > 6000:
            continue

        attrs = " ".join(
            clean(x)
            for x in (
                node.get("class", ""),
                node.get("id", ""),
                node.get("data-product", ""),
                node.get("data-product-name", ""),
                node.get("data-testid", ""),
            )
            if clean(x)
        )

        blob = f"{attrs} {context}"

        if node.name in {"body", "html"}:
            break

        is_card = (
            "product" in attrs.lower()
            or "card" in attrs.lower()
            or "item" in attrs.lower()
            or node.name in {"article", "li"}
        )

        if is_card and matches(
            context,
            query,
        ):
            return context

        if not fallback and is_card:
            fallback = context

    return fallback


def _extract_product_urls(
    html,
    query=None,
    allow_opaque=False,
):
    """Extract product URLs and report exactly where candidates are rejected.

    The debug counters are intentionally local to this extraction call. This
    lets us distinguish:
      - no /product/ URLs present in the category HTML,
      - product URLs present but not carrying usable local context,
      - URLs rejected by the strict query gate,
      - URLs successfully accepted.

    No selection logic is loosened by these diagnostics.
    """
    soup = BeautifulSoup(
        html or "",
        "html.parser",
    )

    found = []
    seen = set()
    q_tokens = tokens(query or "")

    stats = {
        "html_bytes": len(html or ""),
        "query": clean(query),
        "query_tokens": sorted(q_tokens),
        "anchor_product_hrefs": 0,
        "anchor_normalized_product_urls": 0,
        "anchor_context_direct_match": 0,
        "anchor_card_context_found": 0,
        "anchor_context_query_match": 0,
        "anchor_accepted": 0,
        "structured_product_url_matches": 0,
        "structured_accepted": 0,
        "raw_html_product_url_matches": 0,
        "raw_html_accepted": 0,
        "duplicate_urls": 0,
        "rejected_non_deloox": 0,
        "rejected_not_product": 0,
        "rejected_query_mismatch": 0,
        "rejected_opaque": 0,
        "accepted_total": 0,
        "sample_raw_product_urls": [],
        "sample_rejected_query": [],
    }

    if not q_tokens:
        _dbg(
            "product_url_extraction_debug",
            **stats,
            reason="empty_query",
        )
        return []

    def add(
        raw_url,
        context="",
        source="unknown",
    ):
        if not raw_url:
            return False

        raw_url = (
            clean(raw_url)
            .replace("\\/", "/")
        )

        if raw_url.startswith(
            (
                "javascript:",
                "mailto:",
                "#",
            )
        ):
            return False

        url = (
            urljoin(
                BASE_URL,
                raw_url,
            )
            .split("#")[0]
            .split("?")[0]
        )

        try:
            parsed = urlparse(url)
        except Exception:
            return False

        if parsed.netloc.lower() not in {
            "deloox.com",
            "www.deloox.com",
        }:
            stats["rejected_non_deloox"] += 1
            return False

        if "/product/" not in parsed.path.lower():
            stats["rejected_not_product"] += 1
            return False

        if url in seen:
            stats["duplicate_urls"] += 1
            return False

        if not allow_opaque and not matches(
            f"{context} {url}",
            query,
        ):
            stats["rejected_query_mismatch"] += 1

            if len(stats["sample_rejected_query"]) < 10:
                stats["sample_rejected_query"].append(
                    {
                        "source": source,
                        "url": url,
                        "context": clean(context)[:300],
                    }
                )

            return False

        seen.add(url)
        found.append(url)

        if source == "anchor":
            stats["anchor_accepted"] += 1
        elif source == "structured":
            stats["structured_accepted"] += 1
        elif source == "raw_html":
            stats["raw_html_accepted"] += 1

        stats["accepted_total"] += 1
        return True

    # ---------------------------------------------------------
    # 1) NORMAL <a> PRODUCT LINKS
    # ---------------------------------------------------------
    for a in soup.find_all(
        "a",
        href=True,
    ):
        href = clean(
            a.get("href", "")
        )

        if "/product/" not in href.lower():
            continue

        stats["anchor_product_hrefs"] += 1

        context_parts = [
            a.get_text(
                " ",
                strip=True,
            ),
            a.get("aria-label", ""),
            a.get("title", ""),
            a.get("data-name", ""),
            a.get(
                "data-product-name",
                "",
            ),
        ]

        context = " ".join(
            clean(x)
            for x in context_parts
            if clean(x)
        )

        if matches(
            context,
            query,
        ):
            stats["anchor_context_direct_match"] += 1
            stats["anchor_context_query_match"] += 1
        else:
            card_context = _product_card_context(
                a,
                query,
            )

            if card_context:
                stats["anchor_card_context_found"] += 1
                context = card_context

                if matches(
                    context,
                    query,
                ):
                    stats["anchor_context_query_match"] += 1

        normalized_before = len(seen)

        accepted = add(
            href,
            context,
            source="anchor",
        )

        if accepted:
            stats["anchor_normalized_product_urls"] += 1
        elif len(seen) != normalized_before:
            stats["anchor_normalized_product_urls"] += 1

    # ---------------------------------------------------------
    # 2) SERIALIZED / SCRIPT PRODUCT LINKS
    # ---------------------------------------------------------
    raw = (
        html or ""
    ).replace(
        "\\\\/",
        "/",
    ).replace(
        "\\/",
        "/",
    )

    patterns = (
        r'https?://(?:www\.)?deloox\.com[^"\'<>\s]*/product/[^"\'<>\s]+',
        r'(?<![A-Za-z0-9])(?:/|(?:en|it|nl)/)product/[^"\'<>\s]+',
    )

    structured_samples = []

    for tag in soup.find_all(
        [
            "script",
            "div",
            "article",
            "li",
        ]
    ):
        blob = (
            tag.get_text()
            if tag.name == "script"
            else tag.get_text(
                " ",
                strip=True,
            )
        )

        if "/product/" not in blob.lower():
            continue

        for pattern in patterns:
            for match in re.finditer(
                pattern,
                blob,
                re.I,
            ):
                stats["structured_product_url_matches"] += 1

                raw_url = match.group(0)

                if len(structured_samples) < 10:
                    structured_samples.append(
                        raw_url
                    )

                context = _product_url_context(
                    blob,
                    match.start(),
                    match.end(),
                )

                add(
                    raw_url,
                    context,
                    source="structured",
                )

    # ---------------------------------------------------------
    # 3) FINAL RAW HTML PASS
    # ---------------------------------------------------------
    raw_samples = []

    for pattern in patterns:
        for match in re.finditer(
            pattern,
            raw,
            re.I,
        ):
            stats["raw_html_product_url_matches"] += 1

            raw_url = match.group(0)

            if len(raw_samples) < 10:
                raw_samples.append(
                    raw_url
                )

            context = _product_url_context(
                raw,
                match.start(),
                match.end(),
            )

            add(
                raw_url,
                context,
                source="raw_html",
            )

    stats["sample_raw_product_urls"] = (
        structured_samples[:10]
        + [
            x
            for x in raw_samples[:10]
            if x not in structured_samples[:10]
        ]
    )[:10]

    stats["final_product_urls"] = len(found)
    stats["final_sample"] = found[:10]

    _dbg(
        "product_url_extraction_debug",
        **stats,
    )

    return found[:80]

def _absolute_category_url(raw_url):
    """Normalize one Deloox category URL, without scoring or selecting it."""
    if not raw_url:
        return None

    raw_url = clean(raw_url).replace("\\/", "/")

    if raw_url.startswith((
        "javascript:",
        "mailto:",
        "#",
    )):
        return None

    url = (
        urljoin(
            BASE_URL,
            raw_url,
        )
        .split("#")[0]
        .split("?")[0]
    )

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    if parsed.netloc.lower() not in {
        "deloox.com",
        "www.deloox.com",
    }:
        return None

    path = parsed.path.lower()

    if "/category/" not in path or not path.endswith(".html"):
        return None

    return url


def _extract_category_links(html: str):
    """
    Restituisce coppie:
    (category_url, testo_link)

    Questa funzione estrae soltanto le categorie. Non applica la query:
    la rilevanza viene calcolata dopo, prima di seguire la categoria.
    """
    raw = (html or "").replace(
        "\\\\/",
        "/",
    ).replace(
        "\\/",
        "/",
    )

    soup = BeautifulSoup(
        raw,
        "html.parser",
    )

    seen = set()
    categories = []

    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        url = _absolute_category_url(
            anchor.get("href")
        )

        if not url or url in seen:
            continue

        label = anchor.get_text(
            " ",
            strip=True,
        )

        seen.add(url)
        categories.append(
            (url, label)
        )

    for raw_url in re.findall(
        r"""["']((?:/)?(?:[a-z]{2}/)?category/[^"']+\\.html)["']""",
        raw,
        re.I,
    ):
        url = _absolute_category_url(
            raw_url
        )

        if not url or url in seen:
            continue

        seen.add(url)
        categories.append(
            (url, "")
        )

    return categories


def _is_product_url(url: str) -> bool:
    return (
        isinstance(url, str)
        and "/product/" in urlparse(url).path.lower()
    )


_CATEGORY_RE = re.compile(
    r'https?://(?:www\.)?deloox\.com'
    r'(?:/en|/it|/nl)?/category/\d+/[^"\'<>\s]+\.html'
    r'|'
    r'(?<![A-Za-z0-9])'
    r'/(?:en|it|nl)/category/\d+/[^"\'<>\s]+\.html'
    r'|'
    r'(?<![A-Za-z0-9])'
    r'/category/\d+/[^"\'<>\s]+\.html',
    re.I,
)


def _category_slug(url):
    path = urlparse(url).path

    slug = (
        path.rsplit("/", 1)[-1]
        if "/" in path
        else path
    )

    if slug.lower().endswith(".html"):
        slug = slug[:-5]

    return slug


def _category_score(url: str, label: str, query: str) -> int:
    """
    Calcola la rilevanza della categoria usando sia URL sia testo del link.
    """
    wanted = query_tokens(query)
    haystack = norm(f"{url} {label}")

    return sum(
        1
        for token in wanted
        if token in haystack
    )


def _extract_category_links_from_html(
    html,
    query,
    source_url="",
):
    """Extract category URLs from HTML/JSON.

    Unlike the old implementation, this does NOT require the category URL to
    already be an <a>. Deloox can serialize the URL inside scripts or data.
    The URL slug itself is a valid signal; otherwise a small local context is
    used as the label.
    """
    raw = (
        html or ""
    ).replace(
        "\\\\/",
        "/",
    ).replace(
        "\\/",
        "/",
    )

    soup = BeautifulSoup(
        raw,
        "html.parser",
    )

    candidates = {}
    q = clean(query)

    def add(raw_url, label=""):
        if not raw_url:
            return

        raw_url = clean(
            raw_url
        ).replace(
            "\\/",
            "/",
        )

        url = (
            urljoin(
                BASE_URL,
                raw_url,
            )
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

        if not parsed.path.lower().endswith(".html"):
            return

        label = clean(label)

        score = _category_score(
            url,
            label,
            q,
        )

        # A category URL is accepted only if the query is present in its
        # slug or its local label/context. This prevents broad categories
        # from being mistaken for a dedicated Product Line category.
        if score <= 0:
            return

        previous = candidates.get(url)

        if previous is None or score > previous["score"]:
            candidates[url] = {
                "url": url,
                "label": label,
                "score": score,
            }

    # 1) Normal anchors.
    for a in soup.find_all(
        "a",
        href=True,
    ):
        href = clean(
            a.get("href", "")
        )

        if "/category/" not in href.lower():
            continue

        context = " ".join(
            [
                a.get_text(
                    " ",
                    strip=True,
                ),
                a.get("aria-label", ""),
                a.get("title", ""),
                a.get("data-name", ""),
                a.get(
                    "data-category-name",
                    "",
                ),
            ]
        )

        add(
            href,
            context,
        )

    # 2) Raw serialized category URLs.
    for match in _CATEGORY_RE.finditer(raw):
        url = match.group(0)

        left = max(
            0,
            match.start() - 3500,
        )

        right = min(
            len(raw),
            match.end() + 3500,
        )

        local = raw[left:right]

        # Extract likely name/title fields from the local JSON object.
        label = ""

        name_patterns = (
            r'"(?:name|categoryName|category_name|title|label)"\s*:\s*"([^"]{1,300})"',
            r"'(?:name|categoryName|category_name|title|label)'\s*:\s*'([^']{1,300})'",
        )

        for pattern in name_patterns:
            nm = re.search(
                pattern,
                local,
                re.I,
            )

            if nm:
                label = clean(
                    nm.group(1)
                )
                break

        # If no explicit field exists, the slug itself is enough when it
        # contains the complete query.
        add(
            url,
            label,
        )

        # Also allow a local context match for localized/encoded labels.
        if not label and matches(
            local,
            q,
        ):
            add(
                url,
                q,
            )

    # 3) JSON-LD ItemList/breadcrumb structures can contain category URLs.
    for item in soup.find_all(
        [
            "script",
            "meta",
        ]
    ):
        text = (
            item.get_text()
            if item.name == "script"
            else item.get("content", "")
        )

        if "/category/" not in text.lower():
            continue

        for match in _CATEGORY_RE.finditer(
            text
        ):
            add(
                match.group(0),
                q,
            )

    result = list(
        candidates.values()
    )

    result.sort(
        key=lambda x: (
            -x["score"],
            len(x["url"]),
        )
    )

    _dbg(
        "category_link_extraction",
        query=q,
        source=source_url,
        count=len(result),
        matches=result[:20],
    )

    return result


def _category_product_line_links(
    html,
    query,
):
    """Compatibility wrapper for existing diagnostics."""
    return [
        x["url"]
        for x in _extract_category_links_from_html(
            html,
            query,
        )
    ]


def _catalog_filter_links(session):
    """Discover category/Product Line links from a live Deloox catalogue page.

    The important point is that Deloox exposes Product Line links in the
    catalogue navigation. We keep the visible label together with the URL so
    a localized label can resolve a category even when the slug differs.
    """
    global CATALOG_FILTER_LINKS

    if CATALOG_FILTER_LINKS is not None:
        return CATALOG_FILTER_LINKS

    pages = (
        CATALOG_URL,
        BASE_URL + "/en/category/1025540/trending.html?page=1",
        BASE_URL + "/en/category/1025540/trending.html",
    )

    found = []
    seen = set()

    def add(raw_url, label=""):
        if not raw_url:
            return

        raw_url = (
            clean(raw_url)
            .replace("\\/", "/")
            .replace("\\\\/", "/")
        )

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

        # Deloox category pages normally end in .html, but do not make that
        # a hard requirement: the live site can expose navigation URLs with
        # query parameters or locale variants.
        if url in seen:
            return

        seen.add(url)
        found.append((clean(label), url))

    for page_url in pages:
        try:
            r = session.get(
                page_url,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException as exc:
            _dbg(
                "catalog_fetch_error",
                url=page_url,
                error=f"{type(exc).__name__}: {exc}",
            )
            continue

        _dbg(
            "catalog_fetch",
            url=page_url,
            status=r.status_code,
            bytes=len(r.text or ""),
        )

        if r.status_code >= 400:
            continue

        soup = BeautifulSoup(
            r.text or "",
            "html.parser",
        )

        # Normal links: this is the preferred source because label + URL stay
        # associated with each other.
        for a in soup.find_all(
            "a",
            href=True,
        ):
            href = clean(a.get("href", ""))

            if "/category/" not in href.lower():
                continue

            label = " ".join(
                clean(x)
                for x in (
                    a.get_text(
                        " ",
                        strip=True,
                    ),
                    a.get("aria-label", ""),
                    a.get("title", ""),
                    a.get("data-name", ""),
                    a.get(
                        "data-category-name",
                        "",
                    ),
                )
                if clean(x)
            )

            add(href, label)

        # Serialized URLs: keep a local name/title if one exists.
        raw = (
            r.text or ""
        ).replace(
            "\\\\/",
            "/",
        ).replace(
            "\\/",
            "/",
        )

        for match in _CATEGORY_RE.finditer(raw):
            url = match.group(0)

            left = max(
                0,
                match.start() - 3000,
            )
            right = min(
                len(raw),
                match.end() + 3000,
            )

            local = raw[left:right]
            label = ""

            for pattern in (
                r'"(?:name|categoryName|category_name|title|label)"\s*:\s*"([^"]{1,300})"',
                r"'(?:name|categoryName|category_name|title|label)'\s*:\s*'([^']{1,300})'",
            ):
                nm = re.search(
                    pattern,
                    local,
                    re.I,
                )
                if nm:
                    label = clean(nm.group(1))
                    break

            add(url, label)

    CATALOG_FILTER_LINKS = found

    _dbg(
        "catalog_links_discovered",
        count=len(found),
        sample=found[:30],
    )

    return CATALOG_FILTER_LINKS

def _find_catalog_filter_url(
    session,
    query,
):
    """Resolve the real Deloox Product Line/category for a query.

    Priority:
    1. Live catalogue navigation (the real source of Product Line links).
    2. Deloox search-page category links.
    3. Category sitemap.
    4. Cached/discovered catalogue links.

    No category ID is guessed. No product-specific URL is hard-coded.
    """
    q = clean(query)
    q_tokens = tokens(q)

    if not q_tokens:
        return None

    candidates = []

    def add_candidate(
        url,
        label="",
        source="unknown",
        bonus=0,
    ):
        score = _category_score(
            url,
            label,
            q,
        )

        if score <= 0:
            return

        candidates.append(
            (
                score + bonus,
                url,
                clean(label),
                source,
            )
        )

    # ---------------------------------------------------------
    # 1) LIVE CATALOGUE — CRITICAL PATH
    # ---------------------------------------------------------
    catalogue_pages = (
        CATALOG_URL,
        BASE_URL + "/en/category/1025540/trending.html?page=1",
        BASE_URL + "/en/category/1025540/trending.html",
    )

    for catalogue_url in catalogue_pages:
        try:
            r = session.get(
                catalogue_url,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException as exc:
            _dbg(
                "catalog_query_fetch_error",
                query=q,
                url=catalogue_url,
                error=f"{type(exc).__name__}: {exc}",
            )
            continue

        if r.status_code >= 400:
            continue

        extracted = _extract_category_links_from_html(
            r.text,
            q,
            catalogue_url,
        )

        for item in extracted:
            add_candidate(
                item["url"],
                item["label"],
                "live_catalogue",
                1000,
            )

    # ---------------------------------------------------------
    # 2) DIRECT SEARCH PAGE
    # ---------------------------------------------------------
    search_endpoints = (
        BASE_URL + "/en/search?q=" + quote_plus(q),
        BASE_URL + "/en/search?query=" + quote_plus(q),
        BASE_URL + "/en/search?search=" + quote_plus(q),
        BASE_URL + "/en/search?term=" + quote_plus(q),
    )

    for endpoint in search_endpoints:
        try:
            r = session.get(
                endpoint,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        extracted = _extract_category_links_from_html(
            r.text,
            q,
            endpoint,
        )

        for item in extracted:
            add_candidate(
                item["url"],
                item["label"],
                "search",
                500,
            )

    # ---------------------------------------------------------
    # 3) CATEGORY SITEMAP
    # ---------------------------------------------------------
    for url in _sitemap_category_urls(
        session,
        q,
        max_sitemaps=32,
        max_urls=100,
    ):
        add_candidate(
            url,
            "",
            "sitemap",
            400,
        )

    # ---------------------------------------------------------
    # 4) DISCOVERED CATALOGUE LINKS
    # ---------------------------------------------------------
    for label, url in _catalog_filter_links(
        session
    ):
        add_candidate(
            url,
            label,
            "catalog_links",
            200,
        )

    if not candidates:
        _dbg(
            "catalog_match",
            query=q,
            url=None,
            reason="no_matching_category_discovered",
        )
        return None

    # Deduplicate by URL, preserving strongest score.
    best = {}

    for score, url, label, source in candidates:
        current = best.get(url)

        if (
            current is None
            or score > current[0]
        ):
            best[url] = (
                score,
                url,
                label,
                source,
            )

    ranked = sorted(
        best.values(),
        key=lambda x: (
            -x[0],
            len(x[1]),
        ),
    )

    _dbg(
        "catalog_match_candidates",
        query=q,
        candidates=[
            {
                "score": x[0],
                "url": x[1],
                "label": x[2],
                "source": x[3],
            }
            for x in ranked[:20]
        ],
    )

    selected = ranked[0][1]

    _dbg(
        "catalog_match",
        query=q,
        url=selected,
        label=ranked[0][2],
        source=ranked[0][3],
        score=ranked[0][0],
    )

    return selected

def _category_pages(session):
    """Generic fallback category roots only."""
    return (
        BASE_URL + "/category/1000003/fragrances.html",
        BASE_URL + "/category/1075639/womens-fragrances.html",
        BASE_URL + "/category/1075660/womens-perfume.html",
        BASE_URL + "/category/1000054/mens-fragrances.html",
        BASE_URL + "/category/1025540/trending.html",
    )


def _sitemap_category_urls(
    session,
    query,
    max_sitemaps=16,
    max_urls=80,
):
    """Find relevant Deloox category URLs from XML sitemaps."""
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

        try:
            r = session.get(
                sitemap_url,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        body = (
            r.text or ""
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
            r.text,
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

            slug = _category_slug(value)

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

    _dbg(
        "sitemap_category_discovery_done",
        query=query,
        count=len(found),
        urls=found[:20],
    )

    return found


def _pagination_urls(
    page_url,
    max_pages=8,
):
    base = page_url.split("?")[0]

    for page in range(
        1,
        max_pages + 1,
    ):
        yield (
            f"{base}?page={page}"
        )


def _discover_from_categories(
    session,
    query,
    max_urls=120,
):
    """Broad category fallback.

    This is deliberately late in the discovery chain. A broad category is not
    the correct place to start when a dedicated Product Line exists.
    """
    urls = []
    seen = set()
    visited = set()
    max_root_pages = 60

    def add_products(
        html,
        source,
    ):
        candidates = _extract_product_urls(
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
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)

                if len(urls) >= max_urls:
                    return True

        return False

    def next_page_url(
        html,
        current_url,
    ):
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        link = soup.find(
            "link",
            attrs={
                "rel": lambda value: (
                    value
                    and "next"
                    in str(value).lower()
                )
            },
        )

        if link and link.get("href"):
            return (
                urljoin(
                    current_url,
                    clean(
                        link.get("href")
                    ),
                )
                .split("#")[0]
            )

        return None

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

        # Broad generic roots are expensive. We allow pagination on the first
        # three only, and only as a fallback after dedicated discovery failed.
        root_page_limit = (
            max_root_pages
            if root_index < 3
            else 1
        )

        for page_index in range(
            root_page_limit
        ):
            if page_url in visited:
                break

            visited.add(page_url)

            try:
                r = session.get(
                    page_url,
                    headers=HEADERS,
                    timeout=DISCOVERY_TIMEOUT,
                )

                _dbg(
                    "category_fetch",
                    query=query,
                    url=page_url,
                    status=r.status_code,
                    bytes=len(r.text or ""),
                    page=page_index + 1,
                )

            except requests.RequestException as exc:
                _dbg(
                    "category_fetch_error",
                    query=query,
                    url=page_url,
                    error=f"{type(exc).__name__}: {exc}",
                )
                break

            if r.status_code >= 400:
                break

            if (
                root_index == 0
                and page_index == 0
            ):
                _inspect_category_structure(
                    r.text,
                    query,
                    page_url,
                )

            # IMPORTANT:
            # A broad category/root page is not itself the product source.
            # First recognize candidate category links, score them, follow the
            # best matches, and only then scan the followed category for
            # product URLs. This prevents candidate_scan from running against
            # the wrong root page before the category context is established.
            category_links = _extract_category_links(
                r.text,
            )

            scored_categories = []

            for category_url, label in category_links:
                score = _category_score(
                    category_url,
                    label,
                    query,
                )

                if score <= 0:
                    continue

                scored_categories.append(
                    (
                        score,
                        category_url,
                        label,
                    )
                )

            scored_categories.sort(
                key=lambda item: (
                    -item[0],
                    len(item[1]),
                )
            )

            print(
                "DELOOX CATEGORY LINKS:",
                [
                    {
                        "url": url,
                        "label": label,
                        "score": _category_score(
                            url,
                            label,
                            query,
                        ),
                    }
                    for url, label in category_links
                    if _category_score(
                        url,
                        label,
                        query,
                    ) > 0
                ][:10],
                flush=True,
            )

            _dbg(
                "category_link_extraction",
                query=query,
                source=page_url,
                count=len(scored_categories),
                matches=[
                    {
                        "url": category_url,
                        "label": label,
                        "score": score,
                    }
                    for score, category_url, label
                    in scored_categories[:10]
                ],
            )

            for score, category_url, label in scored_categories[:5]:
                if category_url in visited:
                    continue

                visited.add(category_url)

                print(
                    "DELOOX: following category",
                    category_url,
                    "label=",
                    label,
                    "score=",
                    score,
                    flush=True,
                )

                try:
                    category_page = session.get(
                        category_url,
                        headers=HEADERS,
                        timeout=DISCOVERY_TIMEOUT,
                    )

                    _dbg(
                        "category_follow_fetch",
                        query=query,
                        url=category_url,
                        status=category_page.status_code,
                        bytes=len(category_page.text or ""),
                    )

                except requests.RequestException as exc:
                    _dbg(
                        "category_follow_fetch_error",
                        query=query,
                        url=category_url,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                    continue

                if category_page.status_code >= 400:
                    continue

                category_products = _extract_product_urls(
                    category_page.text,
                    query,
                    allow_opaque=False,
                )

                _dbg(
                    "category_product_extraction",
                    query=query,
                    url=category_url,
                    count=len(category_products),
                    sample=category_products[:10],
                )

                print(
                    "DELOOX: category",
                    category_url,
                    "returned",
                    len(category_products),
                    "product URLs",
                    flush=True,
                )

                for product_url in category_products:
                    if not _is_product_url(product_url):
                        continue

                    if product_url in seen:
                        continue

                    seen.add(product_url)
                    urls.append(product_url)

                    if len(urls) >= max_urls:
                        return urls[:max_urls]

            # Se abbiamo trovato categorie pertinenti, il percorso corretto
            # è già stato stabilito: non continuare a paginare il root generico.
            # Altrimenti le stesse categorie vengono riscoperta a ogni pagina,
            # causando richieste inutili (?page=2, ?page=3, ...).
            if scored_categories:
                break

            next_url = next_page_url(
                r.text,
                page_url,
            )

            if not next_url or next_url == page_url:
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
        and len(seen_sitemaps) < max_sitemaps
        and len(product_urls) < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(sitemap_url)

        try:
            r = session.get(
                sitemap_url,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        ctype = (
            r.headers.get("content-type")
            or ""
        ).lower()

        body = (
            r.text or ""
        ).lstrip()

        if (
            "xml" not in ctype
            and not body.startswith(
                (
                    "<?xml",
                    "<urlset",
                    "<sitemapindex",
                )
            )
        ):
            continue

        soup = BeautifulSoup(
            r.text,
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
                    if value not in seen_products:
                        seen_products.add(value)
                        product_urls.append(value)

                        if (
                            len(product_urls)
                            >= max_urls
                        ):
                            break

            elif (
                low.endswith(".xml")
                or "sitemap" in low
            ):
                if value not in seen_sitemaps:
                    pending.append(value)

    return product_urls


def _discover(session, q):
    """Generic Deloox discovery.

    The order is intentional:
    dedicated category -> search/category sitemap -> broad categories ->
    product sitemap.
    """
    urls = []
    seen = set()

    def add_many(
        items,
        source,
    ):
        items = list(items or [])

        _dbg(
            "discovery_candidates",
            query=q,
            source=source,
            count=len(items),
            sample=items[:20],
        )

        for url in items:
            if not _is_product_url(url):
                _dbg(
                    "discovery_rejected_non_product_url",
                    query=q,
                    source=source,
                    url=url,
                )
                continue

            if url not in seen:
                seen.add(url)
                urls.append(url)

                if len(urls) >= 80:
                    return True

        return False

    # =========================================================
    # 1) DEDICATED CATEGORY / PRODUCT LINE
    # =========================================================
    dedicated_category = (
        _find_catalog_filter_url(
            session,
            q,
        )
    )

    if dedicated_category:
        try:
            page = session.get(
                dedicated_category,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )

            _dbg(
                "dedicated_category_fetch",
                query=q,
                url=dedicated_category,
                status=page.status_code,
                bytes=len(page.text or ""),
            )

        except requests.RequestException as exc:
            _dbg(
                "dedicated_category_fetch_error",
                query=q,
                url=dedicated_category,
                error=f"{type(exc).__name__}: {exc}",
            )
            page = None

        if (
            page is not None
            and page.status_code < 400
        ):
            _inspect_category_structure(
                page.text,
                q,
                dedicated_category,
            )

            candidates = _extract_product_urls(
                page.text,
                q,
                allow_opaque=False,
            )

            # Some Deloox category templates render product names in a
            # separate JSON structure while the href itself contains the
            # complete product slug. In that case the strict local-context
            # extractor can legitimately return nothing. Use the product URL
            # slug as a second, still-local signal.
            if not candidates:
                candidates = _product_urls_by_slug(
                    page.text,
                    q,
                )

            _dbg(
                "dedicated_category_candidates",
                query=q,
                url=dedicated_category,
                count=len(candidates),
                sample=candidates[:20],
            )

            if add_many(
                candidates,
                "dedicated_category",
            ):
                return urls[:80]

    # =========================================================
    # 2) CATEGORY SITEMAP
    # =========================================================
    sitemap_categories = (
        _sitemap_category_urls(
            session,
            q,
            max_sitemaps=16,
            max_urls=40,
        )
    )

    for category_url in sitemap_categories:
        if category_url == dedicated_category:
            continue

        try:
            page = session.get(
                category_url,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )

            _dbg(
                "sitemap_category_fetch",
                query=q,
                url=category_url,
                status=page.status_code,
                bytes=len(page.text or ""),
            )

        except requests.RequestException as exc:
            _dbg(
                "sitemap_category_fetch_error",
                query=q,
                url=category_url,
                error=f"{type(exc).__name__}: {exc}",
            )
            continue

        if page.status_code >= 400:
            continue

        candidates = _extract_product_urls(
            page.text,
            q,
            allow_opaque=False,
        )

        if add_many(
            candidates,
            "sitemap_category",
        ):
            return urls[:80]

    # =========================================================
    # 3) Deloox search pages
    # =========================================================
    search_endpoints = [
        BASE_URL + "/en/search?q=" + quote_plus(q),
        BASE_URL + "/en/search?query=" + quote_plus(q),
        BASE_URL + "/en/search?search=" + quote_plus(q),
        BASE_URL + "/en/search?term=" + quote_plus(q),
    ]

    for endpoint in search_endpoints:
        try:
            r = session.get(
                endpoint,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )

            _dbg(
                "search_endpoint",
                query=q,
                url=endpoint,
                status=r.status_code,
                bytes=len(r.text or ""),
            )

        except requests.RequestException as exc:
            _dbg(
                "search_endpoint_error",
                query=q,
                url=endpoint,
                error=f"{type(exc).__name__}: {exc}",
            )
            continue

        if r.status_code >= 400:
            continue

        # First: search-page product URLs.
        candidates = _extract_product_urls(
            r.text,
            q,
            allow_opaque=False,
        )

        _dbg(
            "search_product_candidates",
            query=q,
            source=endpoint,
            count=len(candidates),
            sample=candidates[:10],
        )

        if candidates:
            if add_many(
                candidates,
                "search",
            ):
                return urls[:80]

            # A search page already produced real product candidates. Do not
            # replace that path with category crawling on the same page.
            continue

        # No product candidate on this search page: now extract categories,
        # score them, follow the best ones, and only then extract product URLs.
        category_links = _extract_category_links(
            r.text
        )

        print(
            "DELOOX CATEGORY LINKS:",
            [
                {
                    "url": url,
                    "label": label,
                    "score": _category_score(
                        url,
                        label,
                        q,
                    ),
                }
                for url, label in category_links
                if _category_score(
                    url,
                    label,
                    q,
                ) > 0
            ][:10],
            flush=True,
        )

        scored_categories = []

        for category_url, label in category_links:
            score = _category_score(
                category_url,
                label,
                q,
            )

            if score <= 0:
                continue

            scored_categories.append(
                (
                    score,
                    category_url,
                    label,
                )
            )

        scored_categories.sort(
            key=lambda item: (
                -item[0],
                len(item[1]),
            )
        )

        for score, category_url, label in scored_categories[:5]:
            print(
                "DELOOX: following category",
                category_url,
                "label=",
                label,
                "score=",
                score,
                flush=True,
            )

            try:
                page = session.get(
                    category_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )
            except requests.RequestException:
                continue

            if page.status_code >= 400:
                continue

            category_products = _extract_product_urls(
                page.text,
                q,
                allow_opaque=False,
            )

            print(
                "DELOOX: category",
                category_url,
                "returned",
                len(category_products),
                "product URLs",
                flush=True,
            )

            if add_many(
                category_products,
                "search_category",
            ):
                return urls[:80]

    # =========================================================
    # 4) BROAD CATEGORIES — LAST RESORT
    # =========================================================
    category_candidates = (
        _discover_from_categories(
            session,
            q,
            max_urls=80,
        )
    )

    if add_many(
        category_candidates,
        "broad_categories",
    ):
        return urls[:80]

    # =========================================================
    # 5) PRODUCT SITEMAP — FINAL FALLBACK
    # =========================================================
    sitemap_candidates = (
        _sitemap_product_urls(
            session,
            q,
            max_sitemaps=12,
            max_urls=80,
        )
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

    # Final safety net: discovery must return product URLs only.
    urls = [
        url
        for url in urls
        if _is_product_url(url)
    ]

    return urls[:80]


def diagnostic_discovery(query):
    session = requests.Session()
    out = {
        "query": query,
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

            try:
                r = session.get(
                    root,
                    headers=HEADERS,
                    timeout=DISCOVERY_TIMEOUT,
                )
            except requests.RequestException as exc:
                out["stages"].append(
                    {
                        "stage": "category",
                        "url": root,
                        "error": (
                            type(exc).__name__
                            + ":"
                            + str(exc)
                        ),
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
                    "status": r.status_code,
                    "seconds": elapsed,
                    "bytes": len(r.text),
                }
            )

            if r.status_code >= 400:
                continue

            links = (
                _category_product_line_links(
                    r.text,
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

                try:
                    pr = session.get(
                        link,
                        headers=HEADERS,
                        timeout=DISCOVERY_TIMEOUT,
                    )
                except requests.RequestException as exc:
                    out["stages"].append(
                        {
                            "stage": "product_line_page",
                            "url": link,
                            "error": (
                                type(exc).__name__
                                + ":"
                                + str(exc)
                            ),
                        }
                    )
                    continue

                e1 = round(
                    time.monotonic()
                    - t1,
                    3,
                )

                urls = (
                    _extract_product_urls(
                        pr.text,
                        query,
                    )
                    if pr.status_code < 400
                    else []
                )

                out["stages"].append(
                    {
                        "stage": "product_line_page",
                        "url": link,
                        "status": pr.status_code,
                        "seconds": e1,
                        "bytes": len(pr.text),
                        "product_urls": len(urls),
                        "sample": urls[:5],
                    }
                )

        return out

    finally:
        session.close()


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
            f"name_mismatch: {name}"
        )

    offers = data.get("offers")
    offers = (
        offers
        if isinstance(offers, list)
        else [offers]
    )

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
            soup.get_text(
                " ",
                strip=True,
            )
        )

    if price is None:
        return "missing_price"

    return None


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
            try:
                r = session.get(
                    url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                )

                _dbg(
                    "product_fetch",
                    query=query,
                    url=url,
                    status=r.status_code,
                    bytes=len(r.text or ""),
                )

            except requests.RequestException as exc:
                _dbg(
                    "product_fetch_error",
                    query=query,
                    url=url,
                    error=f"{type(exc).__name__}: {exc}",
                )
                continue

            if r.status_code >= 400:
                _dbg(
                    "product_rejected",
                    query=query,
                    url=url,
                    reason=f"http_{r.status_code}",
                )
                continue

            item = _product(
                url,
                r.text,
                query,
            )

            if not item:
                reason = (
                    _product_rejection_reason(
                        url,
                        r.text,
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

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
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
