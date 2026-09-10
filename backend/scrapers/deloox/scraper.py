"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer Deloox's current category pages and Product Line filter metadata.
- Resolve Product Line URLs from the actual filter DOM/HTML when available.
- Fall back to a bounded set of generic filter URL encodings.
- Follow redirects and inspect the resulting Product Line page.
- Fall back to Deloox search endpoints and sitemap discovery.
- Product pages are parsed through JSON-LD/page content.

IMPORTANT:
- Deloox Belgium only: https://www.deloox.be
- No Playwright dependency.
- No product-specific hardcodes.
"""
from __future__ import annotations

import json
import html as htmllib
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
import time
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.be"
TIMEOUT = 2.5
DISCOVERY_DEADLINE = 7.5
SEARCH_DEADLINE = 12.0
PRODUCT_TIMEOUT = 2.5
PRODUCT_WORKERS = 6
PRODUCT_MAX_CANDIDATES = 12
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


def _diag(stage, **fields):
    parts = [f"{k}={fields[k]!r}" for k in fields]
    suffix = " " + " ".join(parts) if parts else ""
    print(f"DELOOX_DIAG: {stage}{suffix}", flush=True)


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

    m = re.search(
        r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?",
        s,
    )

    if not m:
        return None

    try:
        return round(float(m.group(1).replace(",", ".")), 2)
    except ValueError:
        return None


def availability_from_sources(data, soup):
    """Prefer structured offer availability; never classify from unrelated page text."""
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

    # Secondary: explicit HTML metadata.
    for tag in soup.select(
        '[itemprop="availability"], '
        'meta[property="product:availability"], '
        'meta[name="availability"]'
    ):
        raw = tag.get("content") or tag.get_text(" ", strip=True)
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

    # Last resort: inspect only explicit stock-message elements.
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
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            x = stack.pop(0)

            if isinstance(x, list):
                stack.extend(x)
                continue

            if not isinstance(x, dict):
                continue

            if x.get("@type") == "Product" or "offers" in x:
                return x

            if isinstance(x.get("@graph"), list):
                stack.extend(x["@graph"])

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

    product_line = ""
    text = soup.get_text(" ", strip=True)

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
    offers = offers if isinstance(offers, list) else [offers]

    offer = next(
        (x for x in offers if isinstance(x, dict)),
        {},
    )

    price = parse_price(offer.get("price"))

    if price is None:
        price = parse_price(text)

    if price is None:
        return None

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin")
        or ""
    ) or None

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
            "image": urljoin(url, str(image)) if image else None,
        },
        "identity": {
            "gtin": {
                "value": gtin,
                "source": "jsonld",
            } if gtin else None,
            "mpn": {
                "value": mpn,
                "source": "jsonld",
            } if mpn else None,
            "sku": {
                "value": sku,
                "source": "jsonld",
            } if sku else None,
            "store_product_id": {
                "value": sku,
                "source": "deloox_sku",
            } if sku else None,
        },
        "attributes": {
            "size_ml": {
                "value": selected_size,
                "source": "selected_variant_or_product_name",
            } if selected_size is not None else None,
            "concentration": {
                "value": concentration(name),
                "source": "product_name",
            } if concentration(name) else None,
            "gender": {
                "value": "unknown",
                "source": "not_explicit",
            },
            "packaging_type": {
                "value": "product",
                "source": "default",
            },
            "product_line": {
                "value": product_line,
                "source": "deloox_page",
            } if product_line else None,
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


def _candidate_product_urls(
    html,
    query,
    require_query=True,
    max_results=80,
):
    """Extract Deloox.be product URLs.

    When called on an exact Product Line page, query matching is disabled
    because Deloox product URLs may be numeric or otherwise not contain the
    Product Line name.
    """
    text = str(html or "")
    found = []
    seen = set()
    q_tokens = tokens(query)

    def normalize_url(raw_url):
        raw_url = str(raw_url or "").strip()

        if not raw_url:
            return ""

        for _ in range(3):
            raw_url = (
                raw_url
                .replace("\\/", "/")
                .replace("\\u002F", "/")
                .replace("\\u002f", "/")
            )

        raw_url = htmllib.unescape(raw_url)

        return (
            urljoin(BASE_URL, raw_url)
            .split("#")[0]
            .split("?")[0]
        )

    def add(raw_url, context=""):
        if len(found) >= max_results:
            return

        url = normalize_url(raw_url)

        if not url:
            return

        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {
            "deloox.be",
            "www.deloox.be",
        }:
            return

        if not re.search(
            r"/(?:product|produit)/",
            parsed.path,
            re.I,
        ):
            return

        if url in seen:
            return

        if require_query:
            haystack = f"{context} {url}"

            if not q_tokens.issubset(tokens(haystack)):
                return

        seen.add(url)
        found.append(url)

    try:
        soup = BeautifulSoup(text, "html.parser")

        for a in soup.find_all("a", href=True):
            add(
                a.get("href"),
                a.get_text(" ", strip=True),
            )

            if len(found) >= max_results:
                break

    except Exception:
        pass

    if len(found) >= max_results:
        _diag(
            "candidate_urls",
            total=len(found),
            query=query,
            require_query=require_query,
            sample=found[:10],
        )
        return found

    raw = text

    for _ in range(3):
        raw = (
            raw.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
        )

    raw = htmllib.unescape(raw)

    product_patterns = (
        r'https?://(?:www\.)?deloox\.be/'
        r'(?:en/|it/|nl/|fr/)?'
        r'(?:product|produit)/\d+/[^"\'<>\s]+',

        r'(?<![A-Za-z0-9])/'
        r'(?:en/|it/|nl/|fr/)?'
        r'(?:product|produit)/\d+/[^"\'<>\s]+',

        r'(?<![A-Za-z0-9])/'
        r'(?:en/|it/|nl/|fr/)?'
        r'(?:product|produit)/\d+'
        r'(?:/[^"\'<>\s]+)?',
    )

    for pattern in product_patterns:
        for match in re.finditer(
            pattern,
            raw,
            re.I,
        ):
            candidate = match.group(0)

            lo = max(
                0,
                match.start() - 2500,
            )

            hi = min(
                len(raw),
                match.end() + 2500,
            )

            add(
                candidate,
                raw[lo:hi],
            )

            if len(found) >= max_results:
                break

        if len(found) >= max_results:
            break

    _diag(
        "candidate_urls",
        total=len(found),
        query=query,
        require_query=require_query,
        sample=found[:10],
    )

    return found


def _normalize_deloox_url(raw_url):
    """Normalize only URLs belonging to Deloox Belgium."""
    raw_url = str(raw_url or "").strip()

    if not raw_url:
        return ""

    for _ in range(3):
        raw_url = (
            raw_url
            .replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
        )

    raw_url = htmllib.unescape(raw_url)

    url = urljoin(BASE_URL, raw_url)
    url = url.split("#")[0]

    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    if parsed.netloc.lower() not in {
        "deloox.be",
        "www.deloox.be",
    }:
        return ""

    return url


def _is_category_url(url):
    try:
        path = urlparse(url).path
    except Exception:
        return False

    return bool(
        re.search(
            r"/(?:category|categoria|categorie)/\d+/[^/]+\.html$",
            path,
            re.I,
        )
    )


def _category_url_matches_query(url, query, label=""):
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    slug = parsed.path.rsplit("/", 1)[-1]

    if slug.lower().endswith(".html"):
        slug = slug[:-5]

    q_tokens = tokens(query)

    if not q_tokens:
        return False

    return (
        q_tokens.issubset(tokens(slug))
        or q_tokens.issubset(tokens(label))
    )


def _category_product_line_links(html, query):
    """Discover Product Line/category URLs generically.

    Priority:
    1. Direct /categorie/... URLs already present.
    2. URLs attached to the actual Product Line filter DOM node.
    3. URLs attached to parent/ancestor filter containers.
    4. Category URLs near the Product Line filter's data IDs.
    5. Category IDs explicitly associated with Product Line metadata.
    """
    text = str(html or "")

    links = []
    seen = set()
    q_tokens = tokens(query)

    def add(raw_url, label=""):
        url = _normalize_deloox_url(raw_url)

        if not url:
            return False

        if not _is_category_url(url):
            return False

        if not _category_url_matches_query(
            url,
            query,
            label,
        ):
            return False

        if url not in seen:
            seen.add(url)
            links.append(url)

        return True

    raw = text

    for _ in range(3):
        raw = (
            raw.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
        )

    raw = htmllib.unescape(raw)

    category_pattern = re.compile(
        r'https?(?::)?//(?:www\.)?deloox\.be/'
        r'(?:en/|it/|nl/|fr/)?'
        r'(?:category|categoria|categorie)/'
        r'\d+/[^"\'<>\s]+?\.html'
        r'|(?<![A-Za-z0-9])/'
        r'(?:en/|it/|nl/|fr/)?'
        r'(?:category|categoria|categorie)/'
        r'\d+/[^"\'<>\s]+?\.html',
        re.I,
    )

    raw_category_hits = 0

    for match in category_pattern.finditer(raw):
        raw_category_hits += 1

        candidate = _normalize_deloox_url(
            match.group(0)
        )

        if candidate and _category_url_matches_query(
            candidate,
            query,
        ):
            add(candidate, query)

        if len(links) >= 20:
            break

    # Inspect the actual Product Line filter node.
    if not links and q_tokens:
        try:
            soup = BeautifulSoup(
                raw,
                "html.parser",
            )

            matching_nodes = []

            for node in soup.select(
                'li[data-prpid][data-pvalue-id]'
            ):
                label = clean(
                    node.get("title")
                    or node.get_text(
                        " ",
                        strip=True,
                    )
                )

                if not label:
                    continue

                if not q_tokens.issubset(
                    tokens(label)
                ):
                    continue

                matching_nodes.append(node)

                # Direct node attributes.
                attribute_names = (
                    "href",
                    "data-href",
                    "data-url",
                    "data-link",
                    "data-target",
                    "data-action",
                    "data-filter-url",
                    "data-category-url",
                    "data-category-link",
                )

                for attr in attribute_names:
                    value = node.get(attr)

                    if value and add(
                        value,
                        label,
                    ):
                        break

                # Anchors inside the filter node.
                for a in node.find_all(
                    "a",
                    href=True,
                ):
                    if add(
                        a.get("href"),
                        label,
                    ):
                        break

                if links:
                    break

            # Walk the parent/ancestor structure of the matching filter.
            if not links:
                for node in matching_nodes:
                    current = node

                    for _ in range(5):
                        current = current.parent

                        if current is None:
                            break

                        label = clean(
                            current.get_text(
                                " ",
                                strip=True,
                            )
                        )

                        for attr in (
                            "href",
                            "data-href",
                            "data-url",
                            "data-link",
                            "data-target",
                            "data-action",
                            "data-filter-url",
                            "data-category-url",
                            "data-category-link",
                        ):
                            value = current.get(attr)

                            if value and add(
                                value,
                                label,
                            ):
                                break

                        if links:
                            break

                        for a in current.find_all(
                            "a",
                            href=True,
                        ):
                            if add(
                                a.get("href"),
                                label,
                            ):
                                break

                        if links:
                            break

                    if links:
                        break

        except Exception as exc:
            _diag(
                "category_filter_dom_error",
                error=repr(exc),
            )

    # Search raw HTML around the exact Product Line filter IDs.
    if not links and q_tokens:
        filters = _product_line_filter_ids(
            raw,
            query,
        )

        for item in filters:
            fid = item["filter_id"]
            vid = item["value_id"]
            label = item["label"]

            markers = (
                f'data-prpid="{fid}"',
                f"data-prpid='{fid}'",
                f'data-pvalue-id="{vid}"',
                f"data-pvalue-id='{vid}'",
            )

            positions = []

            for marker in markers:
                start = 0

                while True:
                    pos = raw.find(
                        marker,
                        start,
                    )

                    if pos < 0:
                        break

                    positions.append(pos)
                    start = pos + len(marker)

                    if len(positions) >= 20:
                        break

                if len(positions) >= 20:
                    break

            for pos in positions:
                lo = max(
                    0,
                    pos - 100000,
                )

                hi = min(
                    len(raw),
                    pos + 100000,
                )

                context = raw[lo:hi]

                for match in category_pattern.finditer(
                    context
                ):
                    candidate = _normalize_deloox_url(
                        match.group(0)
                    )

                    if candidate and add(
                        candidate,
                        label,
                    ):
                        break

                if links:
                    break

            if links:
                break

    # Search JSON-like objects where Product Line label and category URL/id
    # may be separated by several attributes.
    if not links and q_tokens:
        query_parts = [
            re.escape(x)
            for x in norm(query).split()
            if x
        ]

        contexts = []

        if query_parts:
            query_re = re.compile(
                r"[^A-Za-z0-9]+".join(query_parts),
                re.I,
            )

            for match in query_re.finditer(raw):
                lo = max(
                    0,
                    match.start() - 100000,
                )

                hi = min(
                    len(raw),
                    match.end() + 100000,
                )

                contexts.append(
                    raw[lo:hi]
                )

                if len(contexts) >= 8:
                    break

        for context in contexts:
            for match in category_pattern.finditer(
                context
            ):
                candidate = _normalize_deloox_url(
                    match.group(0)
                )

                if candidate and add(
                    candidate,
                    query,
                ):
                    break

            if links:
                break

    _diag(
        "category_links",
        accepted=len(links),
        raw_hits=raw_category_hits,
        query=query,
        links=links[:20],
    )

    return links


def _product_line_filter_ids(html, query):
    """Recover Deloox Product Line filter metadata.

    The live category page exposes Product Lines using:
      data-prpid
      data-pvalue-id
      title

    These values are used only as discovery metadata. They are never treated
    as a product/category ID interchangeably.
    """
    soup = BeautifulSoup(
        str(html or ""),
        "html.parser",
    )

    q_tokens = tokens(query)
    found = []
    seen = set()

    for node in soup.select(
        'li[data-prpid][data-pvalue-id]'
    ):
        label = clean(
            node.get("title")
            or node.get_text(
                " ",
                strip=True,
            )
        )

        if not label:
            continue

        if not q_tokens.issubset(
            tokens(label)
        ):
            continue

        prpid = clean(
            node.get("data-prpid")
        )

        pvalue = clean(
            node.get("data-pvalue-id")
        )

        if not prpid or not pvalue:
            continue

        key = (
            prpid,
            pvalue,
            norm(label),
        )

        if key in seen:
            continue

        seen.add(key)

        found.append(
            {
                "filter_id": prpid,
                "value_id": pvalue,
                "label": label,
            }
        )

    _diag(
        "product_line_filter_ids",
        query=query,
        filters=found[:5],
    )

    return found[:5]


def _filter_category_urls(
    root_url,
    html,
    query,
):
    """Build bounded generic Product Line filter probes.

    The filter ID/value pair is discovered from Deloox itself.

    No perfume, category ID or product ID is hardcoded.

    Several common encodings are probed because the filter control is rendered
    in HTML but the canonical Product Line URL is not necessarily an anchor.
    The caller validates the resulting page and also checks response.url after
    redirects.
    """
    filters = _product_line_filter_ids(
        html,
        query,
    )

    urls = []
    seen = set()

    base = root_url.split(
        "?",
        1,
    )[0]

    for item in filters:
        fid = item["filter_id"]
        vid = item["value_id"]

        # These are deliberately generic representations of the same
        # filter/value relationship.
        candidates = (
            f"{base}?filter={fid}-{vid}",
            f"{base}?filters={fid}-{vid}",
            f"{base}?filter={fid}_{vid}",
            f"{base}?filters={fid}_{vid}",
            f"{base}?filter={fid}:{vid}",
            f"{base}?filters={fid}:{vid}",
            f"{base}?filter={fid}={vid}",
            f"{base}?filters={fid}={vid}",
            f"{base}?filter[{fid}]={vid}",
            f"{base}?filters[{fid}]={vid}",
            f"{base}?filter%5B{fid}%5D={vid}",
            f"{base}?filters%5B{fid}%5D={vid}",
            f"{base}?filter[{fid}][]={vid}",
            f"{base}?filters[{fid}][]={vid}",
            f"{base}?filter%5B{fid}%5D%5B%5D={vid}",
            f"{base}?filters%5B{fid}%5D%5B%5D={vid}",
            f"{base}?filter={fid}%3A{vid}",
            f"{base}?filters={fid}%3A{vid}",
            f"{base}?filter={fid}%3D{vid}",
            f"{base}?filters={fid}%3D{vid}",
        )

        for url in candidates:
            if url in seen:
                continue

            seen.add(url)
            urls.append(url)

    _diag(
        "filter_probe_candidates",
        query=query,
        filters=filters,
        count=len(urls),
        sample=urls[:20],
    )

    return filters, urls[:20]


def _extract_urls_from_search_payload(
    payload,
    query,
    max_results=40,
):
    """Extract Deloox product/category URLs from /api/search."""
    results = []
    seen = set()
    q_tokens = tokens(query)

    def add(raw, context=""):
        raw = clean(
            htmllib.unescape(
                str(raw or "")
            )
        )

        if not raw:
            return

        raw = (
            raw.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
        )

        url = (
            urljoin(BASE_URL, raw)
            .split("#")[0]
            .split("?")[0]
        )

        try:
            parsed = urlparse(url)
        except Exception:
            return

        if parsed.netloc.lower() not in {
            "deloox.be",
            "www.deloox.be",
        }:
            return

        if not re.search(
            r"/(?:product|produit|category|categoria|categorie)/",
            parsed.path,
            re.I,
        ):
            return

        if url in seen:
            return

        if re.search(
            r"/(?:category|categoria|categorie)/",
            parsed.path,
            re.I,
        ):
            if q_tokens and not q_tokens.issubset(
                tokens(
                    f"{parsed.path} {context}"
                )
            ):
                return

        seen.add(url)
        results.append(url)

    if isinstance(payload, str):
        try:
            soup = BeautifulSoup(
                payload,
                "html.parser",
            )

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

        except Exception:
            pass

        raw = (
            payload
            .replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
        )

        for m in re.finditer(
            r"https?://(?:www\.)?deloox\.be/"
            r"(?:[^\"'<>\s]+)",
            raw,
            re.I,
        ):
            add(m.group(0))

        return results[:max_results]

    def walk(obj, context=""):
        if len(results) >= max_results:
            return

        if isinstance(obj, dict):
            local = " ".join(
                str(v)
                for v in obj.values()
                if isinstance(
                    v,
                    (str, int, float),
                )
            )

            for k, v in obj.items():
                if isinstance(v, str) and any(
                    x in k.lower()
                    for x in (
                        "url",
                        "href",
                        "link",
                        "slug",
                    )
                ):
                    add(
                        v,
                        f"{context} {local}",
                    )

                elif isinstance(
                    v,
                    (dict, list),
                ):
                    walk(
                        v,
                        f"{context} {local}",
                    )

        elif isinstance(obj, list):
            for item in obj:
                walk(item, context)

        elif isinstance(obj, str) and (
            "/product" in obj.lower()
            or "/produit" in obj.lower()
            or "/categorie" in obj.lower()
        ):
            add(
                obj,
                context,
            )

    walk(payload)

    return results[:max_results]


def _search_api_discovery(
    session,
    query,
    max_urls=80,
):
    """Use Deloox's own search endpoint as a bounded fallback.

    This endpoint is NOT assumed to be the Product Line API.
    """
    endpoint = BASE_URL + "/api/search"

    payloads = (
        {"q": query},
        {"query": query},
        {"search": query},
    )

    found = []
    seen = set()

    for payload in payloads:
        try:
            r = session.get(
                endpoint,
                params=payload,
                headers=HEADERS,
                timeout=5,
            )
        except requests.RequestException:
            continue

        if r.status_code >= 400:
            continue

        body = r.text or ""

        try:
            data = r.json()
        except Exception:
            data = body

        for url in _extract_urls_from_search_payload(
            data,
            query,
            max_results=max_urls,
        ):
            if url not in seen:
                seen.add(url)
                found.append(url)

        if len(found) >= max_urls:
            break

    return found[:max_urls]


def _category_pages(session):
    """Current generic fragrance catalogue roots on Deloox.be."""
    return (
        BASE_URL + "/categorie/1075732/parfum-homme.html",
        BASE_URL + "/categorie/1000063/parfum-femme.html",
        BASE_URL + "/categorie/1075918/parfum-mixte.html",
    )


def _pagination_urls(
    page_url,
    max_pages=3,
):
    """Yield exact target page first, then a bounded page tail."""
    base = page_url.split(
        "?",
        1,
    )[0]

    yield page_url

    for page in range(
        2,
        max_pages + 1,
    ):
        yield f"{base}?page={page}"


def _targeted_category_seed_urls(query):
    """No product-specific category seeds."""
    return []


def _page_contains_product_line(
    html,
    query,
):
    """Check whether a returned page actually contains the requested line."""
    q_tokens = tokens(query)

    if not q_tokens:
        return False

    try:
        soup = BeautifulSoup(
            str(html or ""),
            "html.parser",
        )

        # Prefer explicit Product Line filter labels.
        for node in soup.select(
            'li[data-prpid][data-pvalue-id]'
        ):
            label = clean(
                node.get("title")
                or node.get_text(
                    " ",
                    strip=True,
                )
            )

            if q_tokens.issubset(
                tokens(label)
            ):
                return True

        # Product Line page itself may expose the name in H1/title.
        h1 = soup.find("h1")

        if h1 and q_tokens.issubset(
            tokens(
                h1.get_text(
                    " ",
                    strip=True,
                )
            )
        ):
            return True

        title = soup.find("title")

        if title and q_tokens.issubset(
            tokens(
                title.get_text(
                    " ",
                    strip=True,
                )
            )
        ):
            return True

    except Exception:
        pass

    return False


def _discover_from_categories(
    session,
    query,
    max_urls=120,
):
    urls = []
    seen = set()
    visited = set()

    def add_products(
        html,
        require_query=True,
    ):
        for product_url in _candidate_product_urls(
            html,
            query,
            require_query=require_query,
            max_results=max_urls,
        ):
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)

                if len(urls) >= max_urls:
                    return True

        return False

    roots = list(
        _category_pages(session)
    )

    roots.extend(
        _targeted_category_seed_urls(query)
    )

    _diag(
        "category_roots",
        count=len(roots),
        roots=roots,
        query=query,
    )

    for root in roots:
        try:
            r = session.get(
                root,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            _diag(
                "root_fetch_error",
                url=root,
                error=repr(exc),
            )
            continue

        _diag(
            "root_fetch",
            url=root,
            status=r.status_code,
            bytes=len(r.text or ""),
        )

        if r.status_code >= 400:
            continue

        # Generic root product discovery.
        if add_products(
            r.text,
            require_query=True,
        ):
            return urls[:max_urls]

        # Direct Product Line URL discovery.
        line_links = _category_product_line_links(
            r.text,
            query,
        )

        _diag(
            "root_line_links",
            root=root,
            count=len(line_links),
            links=line_links[:20],
        )

        # Filter metadata discovery.
        filter_info, filter_urls = _filter_category_urls(
            root,
            r.text,
            query,
        )

        _diag(
            "root_filter_ids",
            root=root,
            filters=filter_info,
            probe_urls=filter_urls,
        )

        # First: probe generic filter URL encodings.
        for filter_url in filter_urls:
            if filter_url in visited:
                continue

            visited.add(filter_url)

            try:
                filtered = session.get(
                    filter_url,
                    headers=HEADERS,
                    timeout=5,
                    allow_redirects=True,
                )
            except requests.RequestException as exc:
                _diag(
                    "filter_fetch_error",
                    url=filter_url,
                    error=repr(exc),
                )
                continue

            final_url = (
                filtered.url
                or filter_url
            )

            _diag(
                "filter_fetch",
                url=filter_url,
                status=filtered.status_code,
                bytes=len(filtered.text or ""),
                final_url=final_url,
            )

            if filtered.status_code >= 400:
                continue

            # If Deloox redirected the filter request to a real Product Line
            # page, keep the final URL as a direct discovery candidate.
            if (
                _is_category_url(final_url)
                and _category_url_matches_query(
                    final_url,
                    query,
                )
            ):
                if final_url not in visited:
                    line_links.append(
                        final_url
                    )

                _diag(
                    "filter_redirect_category",
                    source=filter_url,
                    final_url=final_url,
                )

            filter_products = _candidate_product_urls(
                filtered.text,
                query,
                require_query=False,
                max_results=max_urls,
            )

            if filter_products:
                for product_url in filter_products:
                    if product_url not in seen:
                        seen.add(product_url)
                        urls.append(product_url)

                        if len(urls) >= max_urls:
                            return urls[:max_urls]

                if urls:
                    return urls[:max_urls]

        # Second: direct Product Line URLs.
        deduped_line_links = []
        line_seen = set()

        for line_url in line_links:
            if line_url in line_seen:
                continue

            line_seen.add(line_url)
            deduped_line_links.append(line_url)

        for line_url in deduped_line_links:
            if line_url in visited:
                continue

            visited.add(line_url)

            # Exact Product Line page first.
            for page_url in _pagination_urls(
                line_url,
                max_pages=3,
            ):
                if page_url in visited:
                    continue

                visited.add(page_url)

                try:
                    page = session.get(
                        page_url,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                        allow_redirects=True,
                    )
                except requests.RequestException as exc:
                    _diag(
                        "page_fetch_error",
                        url=page_url,
                        error=repr(exc),
                    )
                    continue

                _diag(
                    "page_fetch",
                    url=page_url,
                    status=page.status_code,
                    bytes=len(page.text or ""),
                    final_url=page.url,
                )

                if page.status_code >= 400:
                    continue

                for product_url in _candidate_product_urls(
                    page.text,
                    query,
                    require_query=False,
                    max_results=max_urls,
                ):
                    if product_url not in seen:
                        seen.add(product_url)
                        urls.append(product_url)

                        if len(urls) >= max_urls:
                            return urls[:max_urls]

    _diag(
        "category_discovery_done",
        count=len(urls),
        urls=urls[:20],
        query=query,
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

    pending = list(sitemap_roots)
    seen_sitemaps = set()
    product_urls = []
    seen_products = set()

    def fetch_xml(url):
        try:
            r = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException:
            return None

        if r.status_code >= 400:
            return None

        ctype = (
            r.headers.get("content-type")
            or ""
        ).lower()

        body = r.text.lstrip()

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
            return None

        return r.text

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(product_urls) < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(sitemap_url)

        xml = fetch_xml(sitemap_url)

        _diag(
            "sitemap_product_fetch",
            url=sitemap_url,
            ok=bool(xml),
            pending=len(pending),
        )

        if not xml:
            continue

        soup = BeautifulSoup(
            xml,
            "xml",
        )

        for loc in soup.find_all("loc"):
            value = clean(
                loc.get_text()
            )

            if not value:
                continue

            low = value.lower()

            if re.search(
                r"/(?:product|produit)/",
                low,
                re.I,
            ):
                if query_tokens.issubset(
                    tokens(value)
                ):
                    if value not in seen_products:
                        seen_products.add(value)
                        product_urls.append(value)

                        if len(product_urls) >= max_urls:
                            break

            elif (
                low.endswith(".xml")
                or "sitemap" in low
            ):
                if value not in seen_sitemaps:
                    pending.append(value)

    return product_urls


def _sitemap_category_urls(
    session,
    query,
    max_sitemaps=12,
    max_urls=30,
):
    """Discover relevant Deloox.be category/Product Line pages from sitemaps."""
    query_tokens = tokens(query)

    if not query_tokens:
        return []

    sitemap_roots = (
        BASE_URL + "/sitemap.xml",
        BASE_URL + "/sitemap_index.xml",
        BASE_URL + "/sitemap-index.xml",
        BASE_URL + "/en/sitemap.xml",
    )

    pending = list(sitemap_roots)
    seen_sitemaps = set()
    category_urls = []
    seen_categories = set()

    while (
        pending
        and len(seen_sitemaps) < max_sitemaps
        and len(category_urls) < max_urls
    ):
        sitemap_url = pending.pop(0)

        if sitemap_url in seen_sitemaps:
            continue

        seen_sitemaps.add(sitemap_url)

        try:
            r = session.get(
                sitemap_url,
                headers=HEADERS,
                timeout=TIMEOUT,
            )
        except requests.RequestException as exc:
            _diag(
                "sitemap_category_error",
                url=sitemap_url,
                error=repr(exc),
            )
            continue

        _diag(
            "sitemap_category_fetch",
            url=sitemap_url,
            status=r.status_code,
            bytes=len(r.text or ""),
        )

        if r.status_code >= 400:
            continue

        body = (
            r.text or ""
        ).lstrip()

        ctype = (
            r.headers.get("content-type")
            or ""
        ).lower()

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

            if (
                re.search(
                    r"/(?:category|categoria|categorie)/",
                    low,
                )
                and low.endswith(".html")
            ):
                slug = low.rsplit(
                    "/",
                    1,
                )[-1][:-5]

                if (
                    query_tokens.issubset(
                        tokens(slug)
                    )
                    and value not in seen_categories
                ):
                    seen_categories.add(value)
                    category_urls.append(value)

                    if len(category_urls) >= max_urls:
                        break

            elif (
                low.endswith(".xml")
                or "sitemap" in low
            ):
                if value not in seen_sitemaps:
                    pending.append(value)

    _diag(
        "sitemap_category_done",
        count=len(category_urls),
        urls=category_urls[:30],
        query=query,
    )

    return category_urls[:max_urls]


def _fast_http_get(session, url, timeout=2.5):
    """Small bounded HTTP GET used by the live search path."""
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
        if response.status_code >= 400:
            return None
        return response
    except requests.RequestException:
        return None


def _discover_fast(session, query, deadline):
    """Fast, bounded Deloox discovery.

    The previous implementation walked several catalogue layers sequentially.
    That made one slow Deloox page consume most of the store budget before the
    actual product page was ever reached.

    The live path now probes independent Deloox discovery surfaces concurrently.
    It never embeds a perfume/product URL: URLs are extracted from the live
    response and the final product page remains the authority for matching.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    urls = []
    seen = set()
    lock = None

    roots = list(_category_pages(session))
    endpoints = [
        BASE_URL + "/en/search?query=" + quote_plus(query),
        BASE_URL + "/en/search?q=" + quote_plus(query),
        BASE_URL + "/fr/recherche?query=" + quote_plus(query),
        BASE_URL + "/nl/zoeken?query=" + quote_plus(query),
    ]

    # Search endpoints are usually the cheapest discovery surface. Category
    # roots are included in the same wave because Deloox can expose products
    # there even when its search route is unavailable.
    targets = []
    for url in endpoints + roots:
        if url not in targets:
            targets.append(url)

    def probe(url):
        remaining = max(0.8, min(2.5, deadline - time.monotonic()))
        if remaining <= 0:
            return url, []
        response = _fast_http_get(session, url, timeout=remaining)
        if not response:
            return url, []
        html = response.text or ""
        is_search_surface = "/search" in url.lower() or "/recherche" in url.lower() or "/zoeken" in url.lower()
        candidates = _candidate_product_urls(
            html,
            query,
            require_query=not is_search_surface,
            max_results=20,
        )

        # If a category page exposes the requested Product Line as a filter,
        # recover its live category URL and inspect that page too.
        if not candidates:
            line_links = _category_product_line_links(html, query)
            for line_url in line_links[:2]:
                if time.monotonic() >= deadline:
                    break
                line_response = _fast_http_get(
                    session,
                    line_url,
                    timeout=max(
                        0.8,
                        min(2.0, deadline - time.monotonic()),
                    ),
                )
                if line_response:
                    candidates.extend(
                        _candidate_product_urls(
                            line_response.text or "",
                            query,
                            require_query=False,
                            max_results=20,
                        )
                    )
                    if candidates:
                        break

        return url, candidates

    max_workers = min(8, len(targets))
    pool = ThreadPoolExecutor(max_workers=max_workers)
    futures = [pool.submit(probe, url) for url in targets]
    try:
        pending = set(futures)
        while pending and time.monotonic() < deadline:
            remaining = max(0.05, deadline - time.monotonic())
            done = []
            for future in as_completed(pending, timeout=remaining):
                done.append(future)
                if time.monotonic() >= deadline:
                    break

            for future in done:
                pending.discard(future)
                try:
                    source_url, candidates = future.result(timeout=0)
                except Exception:
                    continue

                for candidate in candidates:
                    if candidate not in seen:
                        seen.add(candidate)
                        urls.append(candidate)

                if len(urls) >= 12:
                    return urls[:12]
    except TimeoutError:
        pass
    finally:
        # Never wait for a stuck network worker here. The store-level timeout
        # in main.py is a second safety net, so this executor must not defeat it.
        pool.shutdown(wait=False, cancel_futures=True)

    return urls[:12]


def _discover(session, q):
    """Discover Deloox products with one strict wall-clock budget."""
    started = time.monotonic()
    deadline = started + DISCOVERY_DEADLINE

    _diag(
        "discover_start",
        query=q,
        base_url=BASE_URL,
        deadline_seconds=DISCOVERY_DEADLINE,
    )

    urls = _discover_fast(session, q, deadline)

    elapsed = time.monotonic() - started
    _diag(
        "discover_fast_done",
        count=len(urls),
        urls=urls[:20],
        query=q,
        elapsed=round(elapsed, 3),
    )

    if urls or time.monotonic() >= deadline:
        return urls[:12]

    # Only use the API if real time remains. Never extend the discovery budget.
    remaining = deadline - time.monotonic()
    if remaining > 0.15:
        try:
            api_urls = _search_api_discovery_bounded(
                session,
                q,
                timeout=remaining,
                max_urls=12,
            )
        except Exception:
            api_urls = []

        if api_urls:
            _diag(
                "discover_api_done",
                count=len(api_urls),
                urls=api_urls[:20],
                query=q,
                elapsed=round(time.monotonic() - started, 3),
            )
            return api_urls[:12]

    _diag(
        "discover_done",
        count=0,
        query=q,
        elapsed=round(time.monotonic() - started, 3),
    )
    return []

def _search_api_discovery_bounded(session, query, timeout=2.0, max_urls=12):
    """Bounded variant of the legacy API discovery helper."""
    endpoint = BASE_URL + "/api/search"
    payloads = (
        {"q": query},
        {"query": query},
        {"search": query},
    )

    found = []
    seen = set()

    for payload in payloads:
        if timeout <= 0:
            break
        started = time.monotonic()
        try:
            request_timeout = min(timeout, 1.8)
            if request_timeout <= 0.15:
                break
            response = session.get(
                endpoint,
                params=payload,
                headers=HEADERS,
                timeout=request_timeout,
            )
        except requests.RequestException:
            timeout -= time.monotonic() - started
            continue

        timeout -= time.monotonic() - started
        if response.status_code >= 400:
            continue

        try:
            data = response.json()
        except Exception:
            data = response.text or ""

        for url in _extract_urls_from_search_payload(
            data,
            query,
            max_results=max_urls,
        ):
            if url not in seen:
                seen.add(url)
                found.append(url)
                if len(found) >= max_urls:
                    return found[:max_urls]

    return found[:max_urls]


def search(query):
    """Return Deloox offers without allowing the store to block ScentHunter."""
    query = clean(query)
    if not query:
        return []

    search_deadline = time.monotonic() + SEARCH_DEADLINE
    session = requests.Session()

    try:
        discovered = _discover(
            session,
            query,
        )

        if not discovered:
            return []

        remaining = search_deadline - time.monotonic()
        if remaining <= 0:
            _diag(
                "search_deadline_before_products",
                query=query,
            )
            return []

        from concurrent.futures import ThreadPoolExecutor, as_completed

        def fetch_one(url):
            local_remaining = max(
                0.8,
                min(
                    PRODUCT_TIMEOUT,
                    search_deadline - time.monotonic(),
                ),
            )
            if local_remaining <= 0:
                return None

            try:
                response = session.get(
                    url,
                    headers=HEADERS,
                    timeout=local_remaining,
                    allow_redirects=True,
                )
            except requests.RequestException:
                return None

            if response.status_code >= 400:
                return None

            final_url = (
                response.url
                or url
            )

            return _product(
                final_url,
                response.text,
                query,
            )

        results = []
        seen = set()

        # Fetch only a small candidate set. Deloox's product pages are
        # independent, so concurrency is the important performance gain.
        max_workers = min(
            PRODUCT_WORKERS,
            len(discovered),
        )

        pool = ThreadPoolExecutor(max_workers=max_workers)
        futures = [
            pool.submit(fetch_one, url)
            for url in discovered[:PRODUCT_MAX_CANDIDATES]
        ]
        try:
            pending = set(futures)
            while pending and time.monotonic() < search_deadline:
                remaining = max(0.05, search_deadline - time.monotonic())
                done = []
                try:
                    for future in as_completed(pending, timeout=remaining):
                        done.append(future)
                        if time.monotonic() >= search_deadline:
                            break
                except TimeoutError:
                    pass

                for future in done:
                    pending.discard(future)
                    try:
                        item = future.result(timeout=0)
                    except Exception:
                        continue

                    if not item:
                        continue

                    sku_value = None
                    sku = item["identity"].get("sku")
                    if sku:
                        sku_value = sku.get("value")

                    final_url = (
                        item.get("url")
                        or ""
                    ).rstrip("/")

                    key = (
                        final_url,
                        sku_value,
                    )

                    if key in seen:
                        continue

                    seen.add(key)
                    results.append(item)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        # Stable display order: bottle size first, then price.
        results.sort(
            key=lambda item: (
                (
                    item.get("attributes", {})
                    .get("size_ml", {})
                    .get("value")
                    if isinstance(
                        item.get("attributes", {}).get("size_ml"),
                        dict,
                    )
                    else None
                ) is None,
                (
                    item.get("attributes", {})
                    .get("size_ml", {})
                    .get("value")
                    if isinstance(
                        item.get("attributes", {}).get("size_ml"),
                        dict,
                    )
                    else 999999
                ),
                float(item.get("offer", {}).get("price") or 999999),
            )
        )

        _diag(
            "search_done",
            query=query,
            count=len(results),
            elapsed=round(
                SEARCH_DEADLINE
                - max(
                    0.0,
                    search_deadline - time.monotonic(),
                ),
                3,
            ),
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
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
