"""Deloox adapter for ScentHunter.

Discovery strategy:
- Prefer Deloox's current category pages and their Product line filter links.
- Fall back to Deloox search endpoints and sitemap discovery.
- Product pages are parsed through JSON-LD/page content.
"""
from __future__ import annotations

import json
import html as htmllib
import re
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Deloox"
BASE_URL = "https://www.deloox.be"
TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "en-GB,en;q=0.9",
}


def _diag(stage, **fields):
    parts = [f"{k}={fields[k]!r}" for k in fields]
    suffix = " " + " ".join(parts) if parts else ""
    print(f"DELOOX_DIAG: {stage}{suffix}", flush=True)


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", clean(v).lower())).strip()


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
    m = re.search(r"(?:€\s*)?(\d{1,4}(?:[.,]\d{2})?)(?:\s*€)?", s)
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
            raw = offer.get("availability") or offer.get("availabilityStatus") or offer.get("stock")
            if raw:
                t = norm(raw)
                if any(x in t for x in ("instock", "in stock", "available")):
                    return "in_stock"
                if any(x in t for x in ("outofstock", "out of stock", "soldout", "sold out", "unavailable", "not available")):
                    return "out_of_stock"

    # Secondary: explicit HTML metadata, not the full page text.
    for tag in soup.select('[itemprop="availability"], meta[property="product:availability"], meta[name="availability"]'):
        raw = tag.get("content") or tag.get_text(" ", strip=True)
        t = norm(raw)
        if any(x in t for x in ("instock", "in stock", "available")):
            return "in_stock"
        if any(x in t for x in ("outofstock", "out of stock", "soldout", "sold out", "unavailable", "not available")):
            return "out_of_stock"

    # Last resort: inspect only elements whose own text is an explicit stock message.
    for node in soup.find_all(string=re.compile(r"\b(?:in stock|out of stock|sold out|not available|unavailable)\b", re.I)):
        t = norm(node)
        if "out of stock" in t or "sold out" in t or "not available" in t or "unavailable" in t:
            return "out_of_stock"
        if "in stock" in t:
            return "in_stock"

    return "unknown"


def _selected_size(soup, data, h1_name):
    """Extract the actually selected bottle size, avoiding stale JSON-LD names."""
    # H1 is authoritative when it contains a size.
    m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", h1_name or "", re.I)
    if m:
        return int(m.group(1))

    # Selected/checked form controls are the best source for variant pages.
    selectors = [
        'input[type="radio"][checked]',
        'input[type="radio"][aria-checked="true"]',
        'input[checked][name*="size" i]',
        'option[selected]',
        '[aria-selected="true"]',
    ]
    for selector in selectors:
        for node in soup.select(selector):
            chunks = [node.get("value", ""), node.get("aria-label", ""), node.get("data-value", ""), node.get("data-size", ""), node.get_text(" ", strip=True)]
            parent = node.parent
            if parent:
                chunks.append(parent.get_text(" ", strip=True))
            grand = parent.parent if parent else None
            if grand:
                chunks.append(grand.get_text(" ", strip=True))
            blob = " ".join(chunks)
            m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", blob, re.I)
            if m:
                return int(m.group(1))

    # Fallback to structured name only after H1/selected controls.
    structured_name = clean(data.get("name")) if isinstance(data, dict) else ""
    m = re.search(r"(?<!\d)(\d{1,4})\s*ml\b", structured_name, re.I)
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
    h1_name = clean(h1.get_text(" ", strip=True)) if h1 else ""
    # Deloox JSON-LD can contain a stale/SEO size (e.g. 30 ml) while the
    # visible product page offers 50/100 ml. Prefer the visible H1.
    name = h1_name or clean(data.get("name"))

    if not name or not matches(name, query):
        return None

    # Deloox product pages expose the product line separately.  Keep it
    # available as extra source context, but use the actual product name
    # for the strict query match.
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
    offer = next((x for x in offers if isinstance(x, dict)), {})

    price = parse_price(offer.get("price"))
    if price is None:
        price = parse_price(text)
    if price is None:
        return None

    gtin = clean(data.get("gtin13") or data.get("gtin") or "") or None
    mpn = clean(data.get("mpn") or "") or None
    sku = clean(data.get("sku") or "") or None

    image = data.get("image")
    if isinstance(image, list):
        image = image[0] if image else None

    avail = availability_from_sources(data, soup)
    selected_size = _selected_size(soup, data, h1_name)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": clean(brand),
            "url": url,
            "image": urljoin(url, str(image)) if image else None,
        },
        "identity": {
            "gtin": {"value": gtin, "source": "jsonld"} if gtin else None,
            "mpn": {"value": mpn, "source": "jsonld"} if mpn else None,
            "sku": {"value": sku, "source": "jsonld"} if sku else None,
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
            "gender": {"value": "unknown", "source": "not_explicit"},
            "packaging_type": {"value": "product", "source": "default"},
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
        "raw_data": {"jsonld": data},
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": url,
        "available": avail == "in_stock",
    }


def _candidate_product_urls(html, query, require_query=True, max_results=80):
    """Extract Deloox.be product URLs from anchors and serialized HTML.

    Discovery is intentionally generic.  On a generic catalogue page we keep
    the query as a cheap filter; once an exact Product Line page has been
    discovered, ``require_query=False`` lets us collect its product links
    even when Deloox uses numeric product URLs or stores the product title in
    a separate JSON object.  The authoritative query validation remains in
    ``_product()``.
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
        return urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]

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
        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return
        if not re.search(r"/(?:product|produit)/", parsed.path, re.I):
            return
        if url in seen:
            return

        if require_query:
            haystack = f"{context} {url}"
            if not q_tokens.issubset(tokens(haystack)):
                return

        seen.add(url)
        found.append(url)

    # DOM anchors.  This path is deliberately tolerant of localized
    # /product/ and /produit/ URLs.
    try:
        soup = BeautifulSoup(text, "html.parser")
        for a in soup.find_all("a", href=True):
            add(a.get("href"), a.get_text(" ", strip=True))
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

    # Raw HTML / JSON / JS.  Deloox frequently serializes slashes and may
    # store the URL without the product title in the same field.
    raw = text
    for _ in range(3):
        raw = (
            raw.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
        )
    raw = htmllib.unescape(raw)

    product_patterns = (
        r'https?://(?:www\.)?deloox\.be/(?:en/|it/|nl/|fr/)?'
        r'(?:product|produit)/\d+/[^"\'<>\s]+',
        r'(?<![A-Za-z0-9])/(?:en/|it/|nl/|fr/)?'
        r'(?:product|produit)/\d+/[^"\'<>\s]+',
        r'(?<![A-Za-z0-9])/(?:en/|it/|nl/|fr/)?'
        r'(?:product|produit)/\d+(?:/[^"\'<>\s]+)?',
    )

    for pattern in product_patterns:
        for match in re.finditer(pattern, raw, re.I):
            candidate = match.group(0)
            lo = max(0, match.start() - 2500)
            hi = min(len(raw), match.end() + 2500)
            add(candidate, raw[lo:hi])
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


def _category_product_line_links(html, query):
    """Discover Product Line/category URLs matching ``query`` on Deloox.be.

    The catalogue pages are multi-megabyte documents.  Do not build a full
    DOM tree unless the cheap raw scan fails.  The live site may represent a
    Product Line in several ways:
      - a literal /categorie/<id>/<slug>.html URL;
      - an escaped URL inside JSON/JS;
      - a numeric category/product-line id next to the Product Line label;
      - a JSON object where the label and URL/id are separated by several
        kilobytes.

    All paths remain generic; no perfume, category id or product id is
    hardcoded.
    """
    text = str(html or "")
    links = []
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
        return urljoin(BASE_URL, raw_url).split("#")[0].split("?")[0]

    def add(raw_url, label=""):
        url = normalize_url(raw_url)
        if not url:
            return False
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return False
        if not re.search(r"/(?:category|categoria|categorie)/", parsed.path, re.I):
            return False

        slug = parsed.path.rsplit("/", 1)[-1]
        if slug.lower().endswith(".html"):
            slug = slug[:-5]

        if q_tokens and not (
            q_tokens.issubset(tokens(slug))
            or q_tokens.issubset(tokens(label))
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

    # 1) Cheapest and strongest case: the Product Line URL itself is present.
    category_pattern = re.compile(
        r'https?(?::)?//(?:www\.)?deloox\.be/'
        r'(?:en/|it/|nl/|fr/)?(?:category|categoria|categorie)/'
        r'\d+/[^"\'<>\s]+?\.html'
        r'|(?<![A-Za-z0-9])/(?:en/|it/|nl/|fr/)?'
        r'(?:category|categoria|categorie)/\d+/[^"\'<>\s]+?\.html',
        re.I,
    )

    raw_category_hits = 0
    for match in category_pattern.finditer(raw):
        raw_category_hits += 1
        add(match.group(0))
        if len(links) >= 20:
            break

    # 2) The query can be rendered with markup/JSON punctuation between words.
    # Find its real position in the raw document, then inspect a bounded
    # neighbourhood for a category URL or category id.
    if not links and q_tokens:
        query_parts = [re.escape(x) for x in norm(query).split() if x]
        contexts = []
        if query_parts:
            query_re = re.compile(
                r"[^A-Za-z0-9]+".join(query_parts), re.I
            )
            for match in query_re.finditer(raw):
                lo = max(0, match.start() - 50000)
                hi = min(len(raw), match.end() + 50000)
                contexts.append(raw[lo:hi])
                if len(contexts) >= 12:
                    break

        # First try an actual category URL anywhere near the Product Line
        # label.  This does not assume that the URL itself contains the slug.
        for context in contexts:
            for match in category_pattern.finditer(context):
                if add(match.group(0), query):
                    break
            if links:
                break

        # Then recover a category/product-line id from common structured-data
        # representations and construct the canonical Belgian URL.
        if not links:
            candidate_ids = []
            id_patterns = (
                r'(?:categoryId|category_id|productLineId|product_line_id)'
                r'\s*["\']?\s*[:=]\s*["\']?(\d{4,9})',
                r'(?:data-category-id|data-product-line-id)'
                r'\s*=\s*["\']?(\d{4,9})',
                r'(?:category|categorie|product.?line)'
                r'[^0-9]{0,160}(\d{4,9})',
                r'(\d{4,9})[^A-Za-z]{0,160}'
                r'(?:category|categorie|product.?line)',
            )

            for context in contexts:
                for pattern in id_patterns:
                    for value in re.findall(pattern, context, re.I):
                        if value not in candidate_ids:
                            candidate_ids.append(value)

            slug = re.sub(
                r"[^a-zA-Z0-9]+", "-", query
            ).strip("-").lower()

            for category_id in candidate_ids[:30]:
                add(
                    f"{BASE_URL}/categorie/{category_id}/{slug}.html",
                    query,
                )
                if links:
                    break

            _diag(
                "category_id_recovery",
                query=query,
                candidate_ids=candidate_ids[:30],
                context_count=len(contexts),
            )

    # 3) Last cheap fallback: inspect only the small DOM elements containing
    # the exact Product Line text.  This is used only when raw discovery
    # failed, so the normal 6–7 MB category request is not repeatedly parsed.
    if not links and q_tokens:
        try:
            soup = BeautifulSoup(raw, "html.parser")
            for node in soup.find_all(string=re.compile(r"liquid|product", re.I)):
                label = clean(node)
                if not label or not q_tokens.issubset(tokens(label)):
                    continue
                parent = node.parent
                if parent is None:
                    continue
                for a in parent.find_all("a", href=True):
                    if add(a.get("href"), label):
                        break
                if links:
                    break
        except Exception as exc:
            _diag("category_dom_fallback_error", error=repr(exc))

    _diag(
        "category_links",
        accepted=len(links),
        raw_hits=raw_category_hits,
        query=query,
        links=links[:20],
    )
    return links



def _product_line_filter_ids(html, query):
    """Recover the Product Line filter value assigned by Deloox itself.

    The live category page exposes the selected Product Line as:
    <li data-prpid="12" data-pvalue-id="..." title="...">.
    This is more reliable than trying to infer a category id from the label.
    """
    soup = BeautifulSoup(str(html or ""), "html.parser")
    q_tokens = tokens(query)
    found = []
    seen = set()
    for node in soup.select('li[data-prpid][data-pvalue-id]'):
        label = clean(node.get("title") or node.get_text(" ", strip=True))
        if not label or not q_tokens.issubset(tokens(label)):
            continue
        prpid = clean(node.get("data-prpid"))
        pvalue = clean(node.get("data-pvalue-id"))
        if not prpid or not pvalue:
            continue
        key = (prpid, pvalue, norm(label))
        if key in seen:
            continue
        seen.add(key)
        found.append({"filter_id": prpid, "value_id": pvalue, "label": label})
    return found[:5]


def _filter_category_urls(root_url, html, query):
    """Try Deloox's common filter-query encodings for the exact Product Line.

    Deloox currently renders the Product Line filter in HTML but does not expose
    the resulting URL as a normal anchor. We therefore recover the site's own
    filter/value ids and probe a very small, bounded set of URL encodings.
    """
    filters = _product_line_filter_ids(html, query)
    urls = []
    seen = set()
    base = root_url.split("?", 1)[0]
    for item in filters:
        fid = item["filter_id"]
        vid = item["value_id"]
        candidates = (
            f"{base}?filter={fid}-{vid}",
            f"{base}?filters={fid}-{vid}",
            f"{base}?filters[{fid}]={vid}",
            f"{base}?filter[{fid}]={vid}",
            f"{base}?filter={fid}%3A{vid}",
        )
        for url in candidates:
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return filters, urls[:5]


def _extract_urls_from_search_payload(payload, query, max_results=40):
    """Extract Deloox product/category URLs from JSON or HTML returned by /api/search."""
    results = []
    seen = set()
    q_tokens = tokens(query)

    def add(raw, context=""):
        raw = clean(htmllib.unescape(str(raw or "")))
        if not raw:
            return
        raw = raw.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
        url = urljoin(BASE_URL, raw).split("#")[0].split("?")[0]
        try:
            parsed = urlparse(url)
        except Exception:
            return
        if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
            return
        if not re.search(r"/(?:product|produit|category|categoria|categorie)/", parsed.path, re.I):
            return
        if url in seen:
            return
        # Product URLs can be numeric and need not contain the query. Category
        # URLs are accepted only when their label/slug carries the query.
        if re.search(r"/(?:category|categoria|categorie)/", parsed.path, re.I):
            if q_tokens and not q_tokens.issubset(tokens(f"{parsed.path} {context}")):
                return
        seen.add(url)
        results.append(url)

    if isinstance(payload, str):
        try:
            soup = BeautifulSoup(payload, "html.parser")
            for a in soup.find_all("a", href=True):
                add(a.get("href"), a.get_text(" ", strip=True))
        except Exception:
            pass
        raw = payload.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
        for m in re.finditer(r"https?://(?:www\.)?deloox\.be/(?:[^\"'<>\s]+)", raw, re.I):
            add(m.group(0))
        return results[:max_results]

    def walk(obj, context=""):
        if len(results) >= max_results:
            return
        if isinstance(obj, dict):
            local = " ".join(str(v) for v in obj.values() if isinstance(v, (str, int, float)))
            for k, v in obj.items():
                if isinstance(v, str) and any(x in k.lower() for x in ("url", "href", "link", "slug")):
                    add(v, f"{context} {local}")
                elif isinstance(v, (dict, list)):
                    walk(v, f"{context} {local}")
        elif isinstance(obj, list):
            for item in obj:
                walk(item, context)
        elif isinstance(obj, str) and ("/product" in obj.lower() or "/produit" in obj.lower() or "/categorie" in obj.lower()):
            add(obj, context)

    walk(payload)
    return results[:max_results]


def _search_api_discovery(session, query, max_urls=80):
    """Use Deloox's own search endpoint as a bounded fallback.

    The page explicitly advertises /api/search through the search input's
    data-url. It is not assumed to be the product-line API; we only accept
    actual Deloox product/category URLs returned by it.
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
            r = session.get(endpoint, params=payload, headers=HEADERS, timeout=5)
        except requests.RequestException:
            continue
        if r.status_code >= 400:
            continue
        body = r.text or ""
        try:
            data = r.json()
        except Exception:
            data = body
        for url in _extract_urls_from_search_payload(data, query, max_results=max_urls):
            if url not in seen:
                seen.add(url)
                found.append(url)
        if len(found) >= max_urls:
            break
    return found[:max_urls]

def _category_pages(session):
    """Current generic fragrance catalog roots on Deloox.be.

    The old /category/... roots are obsolete on deloox.be and return 404.
    The live Belgian site exposes its catalog under /categorie/... .
    These are generic catalog roots, not product-specific seeds.
    """
    return (
        BASE_URL + "/categorie/1075732/parfum-homme.html",
        BASE_URL + "/categorie/1000063/parfum-femme.html",
        BASE_URL + "/categorie/1075918/parfum-mixte.html",
    )



def _pagination_urls(page_url, max_pages=3):
    """Yield the exact target page first, then a small bounded page tail."""
    base = page_url.split("?")[0]
    yield page_url
    for page in range(2, max_pages + 1):
        yield f"{base}?page={page}"


def _targeted_category_seed_urls(query):
    """Return no product-specific category seeds.

    Discovery remains fully generic: matching Product Line/category URLs are
    discovered from Deloox.be itself by _category_product_line_links().
    """
    return []


def _discover_from_categories(session, query, max_urls=120):
    urls = []
    seen = set()
    visited = set()

    def add_products(html):
        for product_url in _candidate_product_urls(html, query):
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)
                if len(urls) >= max_urls:
                    return True
        return False

    roots = list(_category_pages(session))
    roots.extend(_targeted_category_seed_urls(query))
    _diag("category_roots", count=len(roots), roots=roots, query=query)

    for root in roots:
        try:
            r = session.get(root, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            _diag("root_fetch_error", url=root, error=repr(exc))
            continue
        _diag("root_fetch", url=root, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue

        # First inspect the root itself.  This is the only root-page parse.
        if add_products(r.text):
            return urls[:max_urls]

        # Discover the exact Product Line page.  If none is found, do NOT
        # crawl the root's pagination: the old 100-page expansion was the
        # source of the multi-minute diagnostic/search hang.
        line_links = _category_product_line_links(r.text, query)
        _diag("root_line_links", root=root, count=len(line_links), links=line_links[:20])

        # The live page exposes the Product Line filter as data-prpid/value-id
        # but not as an anchor. Probe Deloox's bounded filter URL encodings.
        filter_info, filter_urls = _filter_category_urls(root, r.text, query)
        _diag("root_filter_ids", root=root, filters=filter_info, probe_urls=filter_urls)
        for filter_url in filter_urls:
            if filter_url in visited:
                continue
            visited.add(filter_url)
            try:
                filtered = session.get(filter_url, headers=HEADERS, timeout=5)
            except requests.RequestException as exc:
                _diag("filter_fetch_error", url=filter_url, error=repr(exc))
                continue
            _diag("filter_fetch", url=filter_url, status=filtered.status_code, bytes=len(filtered.text or ""), final_url=filtered.url)
            if filtered.status_code >= 400:
                continue
            filter_products = _candidate_product_urls(filtered.text, query, require_query=False, max_results=max_urls)
            if filter_products:
                for product_url in filter_products:
                    if product_url not in seen:
                        seen.add(product_url)
                        urls.append(product_url)
                        if len(urls) >= max_urls:
                            return urls[:max_urls]
                if urls:
                    return urls[:max_urls]

        for line_url in line_links:
            if line_url in visited:
                continue
            visited.add(line_url)

            # Fetch the exact Product Line page first, then at most 3 pages of
            # that targeted result if necessary.
            for page_url in _pagination_urls(line_url, max_pages=3):
                if page_url in visited:
                    continue
                visited.add(page_url)
                try:
                    page = session.get(page_url, headers=HEADERS, timeout=TIMEOUT)
                except requests.RequestException as exc:
                    _diag("page_fetch_error", url=page_url, error=repr(exc))
                    continue
                _diag("page_fetch", url=page_url, status=page.status_code, bytes=len(page.text or ""))
                if page.status_code >= 400:
                    continue
                for product_url in _candidate_product_urls(
                    page.text, query, require_query=False, max_results=max_urls
                ):
                    if product_url not in seen:
                        seen.add(product_url)
                        urls.append(product_url)
                        if len(urls) >= max_urls:
                            return urls[:max_urls]

    _diag("category_discovery_done", count=len(urls), urls=urls[:20], query=query)
    return urls[:max_urls]

def _sitemap_product_urls(session, query, max_sitemaps=12, max_urls=80):
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
            r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            return None
        if r.status_code >= 400:
            return None

        ctype = (r.headers.get("content-type") or "").lower()
        body = r.text.lstrip()
        if "xml" not in ctype and not body.startswith(
            ("<?xml", "<urlset", "<sitemapindex")
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
        _diag("sitemap_product_fetch", url=sitemap_url, ok=bool(xml), pending=len(pending))
        if not xml:
            continue

        soup = BeautifulSoup(xml, "xml")

        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue

            low = value.lower()

            if re.search(r"/(?:product|produit)/", low, re.I):
                if query_tokens.issubset(tokens(value)):
                    if value not in seen_products:
                        seen_products.add(value)
                        product_urls.append(value)
                        if len(product_urls) >= max_urls:
                            break
            elif low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps:
                    pending.append(value)

    return product_urls


def _sitemap_category_urls(session, query, max_sitemaps=12, max_urls=30):
    """Discover relevant Deloox.be category/Product-line pages from sitemaps."""
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

    while pending and len(seen_sitemaps) < max_sitemaps and len(category_urls) < max_urls:
        sitemap_url = pending.pop(0)
        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)
        try:
            r = session.get(sitemap_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            _diag("sitemap_category_error", url=sitemap_url, error=repr(exc))
            continue
        _diag("sitemap_category_fetch", url=sitemap_url, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue

        body = (r.text or "").lstrip()
        ctype = (r.headers.get("content-type") or "").lower()
        if "xml" not in ctype and not body.startswith(("<?xml", "<urlset", "<sitemapindex")):
            continue

        soup = BeautifulSoup(r.text, "xml")
        for loc in soup.find_all("loc"):
            value = clean(loc.get_text())
            if not value:
                continue
            low = value.lower()
            if re.search(r"/(?:category|categoria|categorie)/", low) and low.endswith(".html"):
                slug = low.rsplit("/", 1)[-1][:-5]
                if query_tokens.issubset(tokens(slug)) and value not in seen_categories:
                    seen_categories.add(value)
                    category_urls.append(value)
                    if len(category_urls) >= max_urls:
                        break
            elif low.endswith(".xml") or "sitemap" in low:
                if value not in seen_sitemaps:
                    pending.append(value)

    _diag("sitemap_category_done", count=len(category_urls), urls=category_urls[:30], query=query)
    return category_urls[:max_urls]


def _discover(session, q):
    """Discover Deloox.be product pages generically for the requested query."""
    urls = []
    seen = set()
    _diag("discover_start", query=q, base_url=BASE_URL)

    # PRIMARY: current category / Product-line structure.
    category_products = _discover_from_categories(session, q, max_urls=80)
    _diag("discover_primary", count=len(category_products), urls=category_products[:20])
    for url in category_products:
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            return urls[:80]

    # SECONDARY: Deloox's own search endpoint, if it exposes product/category URLs.
    api_products = _search_api_discovery(session, q, max_urls=80)
    _diag("discover_api_fallback", count=len(api_products), urls=api_products[:20])
    for url in api_products:
        if re.search(r"/(?:product|produit)/", url, re.I):
            if url not in seen:
                seen.add(url)
                urls.append(url)
                if len(urls) >= 80:
                    return urls[:80]
        else:
            try:
                page = session.get(url, headers=HEADERS, timeout=5)
            except requests.RequestException:
                continue
            if page.status_code >= 400:
                continue
            for product_url in _candidate_product_urls(page.text, q, require_query=False, max_results=80):
                if product_url not in seen:
                    seen.add(product_url)
                    urls.append(product_url)
                    if len(urls) >= 80:
                        return urls[:80]

    # TERTIARY: Product-line/category pages exposed by Deloox.be sitemaps.
    sitemap_categories = _sitemap_category_urls(
        session, q, max_sitemaps=12, max_urls=30
    )
    _diag("discover_sitemap_categories", count=len(sitemap_categories), urls=sitemap_categories[:30])
    for category_url in sitemap_categories:
        try:
            page = session.get(category_url, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException:
            continue
        if page.status_code >= 400:
            continue
        for product_url in _candidate_product_urls(page.text, q):
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)
                if len(urls) >= 80:
                    return urls[:80]

    # QUATERNARY: localized search endpoints, retained as fallback.
    endpoints = [
        BASE_URL + "/en/search?query=" + quote_plus(q),
        BASE_URL + "/en/search?search=" + quote_plus(q),
        BASE_URL + "/en?search=" + quote_plus(q),
        BASE_URL + "/en/search?q=" + quote_plus(q),
        BASE_URL + "/nl/zoeken?query=" + quote_plus(q),
        BASE_URL + "/nl/zoeken?q=" + quote_plus(q),
        BASE_URL + "/fr/recherche?query=" + quote_plus(q),
        BASE_URL + "/fr/recherche?q=" + quote_plus(q),
    ]
    for endpoint in endpoints:
        try:
            r = session.get(endpoint, headers=HEADERS, timeout=TIMEOUT)
        except requests.RequestException as exc:
            _diag("search_endpoint_error", endpoint=endpoint, error=repr(exc))
            continue
        _diag("search_endpoint", endpoint=endpoint, status=r.status_code, bytes=len(r.text or ""))
        if r.status_code >= 400:
            continue
        endpoint_products = _candidate_product_urls(r.text, q)
        _diag("search_endpoint_products", endpoint=endpoint, count=len(endpoint_products), urls=endpoint_products[:20])
        for url in endpoint_products:
            if url not in seen:
                seen.add(url)
                urls.append(url)
        if len(urls) >= 80:
            return urls[:80]

    # LAST RESORT: product sitemap discovery.
    for url in _sitemap_product_urls(session, q, max_sitemaps=12, max_urls=80):
        if url not in seen:
            seen.add(url)
            urls.append(url)
        if len(urls) >= 80:
            break

    _diag("discover_done", count=len(urls), urls=urls[:80], query=q)
    return urls[:80]

def search(query):
    query = clean(query)
    if not query:
        return []

    session = requests.Session()
    results = []
    seen = set()

    try:
        for url in _discover(session, query):
            try:
                r = session.get(url, headers=HEADERS, timeout=TIMEOUT)
            except requests.RequestException:
                continue

            if r.status_code >= 400:
                continue

            item = _product(url, r.text, query)
            if not item:
                continue

            sku_value = None
            sku = item["identity"].get("sku")
            if sku:
                sku_value = sku.get("value")

            key = (url, sku_value)

            if key in seen:
                continue

            seen.add(key)
            results.append(item)

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
