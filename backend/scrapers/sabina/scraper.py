import json
import html
import re
import unicodedata
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
SEARCH_URL = BASE_URL + "/es/buscar"
TIMEOUT = 10
MAX_CANDIDATES = 12

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Referer": BASE_URL + "/es/",
}

PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl|pt)/[^/]+/(\d+)-[^/]+\.html$",
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "by", "ml", "pour",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = value.lower()
    value = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        value,
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query):
    return [
        token
        for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def query_matches(text, query):
    tokens = query_tokens(query)
    normalized = norm(text)
    return bool(tokens) and all(token in normalized for token in tokens)


def normalise_url(url, base_url=BASE_URL):
    if not url:
        return None

    url = clean(url).replace("\\/", "/")
    url = url.replace("\\u002F", "/")

    absolute = urljoin(base_url, url)
    parsed = urlparse(absolute)

    if parsed.scheme not in {"http", "https"}:
        return None

    host = parsed.netloc.lower()
    if host not in {"sabina.com", "www.sabina.com"}:
        return None

    return (
        f"{parsed.scheme}://{parsed.netloc}"
        f"{parsed.path.rstrip('/')}"
    )


def is_product_url(url):
    if not url:
        return False
    return bool(
        PRODUCT_PATH_RE.match(
            urlparse(url).path
        )
    )


def product_id_from_url(url):
    match = PRODUCT_PATH_RE.match(
        urlparse(url).path
    )
    return match.group(1) if match else None


def money_to_float(value):
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = re.sub(
        r"[^\d,.\-]",
        "",
        str(value),
    )

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "")
            text = text.replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def extract_size_ml(*texts):
    combined = " ".join(
        str(text or "")
        for text in texts
    )

    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*"
        r"(?:ml|millilitros?|milliliters?)\b",
        combined,
        re.I,
    )

    if not match:
        return None

    value = float(
        match.group(1).replace(",", ".")
    )

    return int(value) if value.is_integer() else value


CONCENTRATION_RULES = (
    (
        "Extrait de Parfum",
        (
            r"\bextrait\s+(?:de\s+)?parfum\b",
            r"\bextrait\b",
        ),
    ),
    (
        "Eau de Parfum",
        (
            r"\beau\s+de\s+parfum\b",
            r"\bedp\b",
        ),
    ),
    (
        "Eau de Toilette",
        (
            r"\beau\s+de\s+toilette\b",
            r"\bedt\b",
        ),
    ),
    (
        "Eau de Cologne",
        (
            r"\beau\s+de\s+cologne\b",
            r"\bedc\b",
        ),
    ),
    ("Parfum", (r"\bparfum\b",)),
)


def extract_concentration(*texts):
    normalized = norm(
        " ".join(str(text or "") for text in texts)
    )

    for label, patterns in CONCENTRATION_RULES:
        for pattern in patterns:
            if re.search(
                pattern,
                normalized,
                re.I,
            ):
                return label, "product_text"

    return None, None


def extract_gender(*texts):
    normalized = norm(
        " ".join(str(text or "") for text in texts)
    )

    if re.search(
        r"\b(?:hombre|hombres|man|men|masculino|male|"
        r"pour homme|homme|uomo)\b",
        normalized,
    ):
        return "men", "product_text"

    if re.search(
        r"\b(?:mujer|mujeres|woman|women|femenino|female|"
        r"pour femme|femme|donna)\b",
        normalized,
    ):
        return "women", "product_text"

    if re.search(
        r"\b(?:unisex|unisexe|unisexes)\b",
        normalized,
    ):
        return "unisex", "product_text"

    return "unknown", None


def walk_json(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_json(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk_json(child)


def first_jsonld_product(soup, expected_url=None, expected_title=None):
    expected_url = normalise_url(expected_url) if expected_url else None
    expected_path = urlparse(expected_url).path if expected_url else None
    expected_title_norm = norm(expected_title or "")
    candidates = []

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

        for item in walk_json(data):
            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if not any(str(value).lower() == "product" for value in types):
                continue

            score = 0
            item_url = normalise_url(item.get("url"))
            item_path = urlparse(item_url).path if item_url else None
            item_name = clean(item.get("name"))

            if expected_url and item_url == expected_url:
                score += 100
            if expected_path and item_path == expected_path:
                score += 100

            if expected_title_norm and item_name:
                item_name_norm = norm(item_name)
                if item_name_norm == expected_title_norm:
                    score += 80
                elif query_matches(item_name, expected_title):
                    score += 50
                elif query_matches(expected_title, item_name):
                    score += 30

            if item.get("offers"):
                score += 5

            candidates.append((score, item))

    if not candidates:
        return None

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    score, product = candidates[0]

    if (expected_path or expected_title_norm) and score < 30:
        return None

    return product


def meta_content(soup, *selectors):
    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue

        value = (
            node.get("content")
            or node.get("value")
            or node.get_text(" ", strip=True)
        )

        value = clean(value)
        if value:
            return value

    return None


def extract_price_from_html(soup):
    """
    Generic fallback for the current product page.

    Only product-bound metadata/current-price nodes are accepted. This avoids
    accidentally taking a price belonging to a related/recommended product.
    """
    direct = meta_content(
        soup,
        'meta[itemprop="price"]',
        'meta[property="product:price:amount"]',
        'meta[name="product:price:amount"]',
    )

    if direct:
        value = money_to_float(direct)
        if value is not None:
            return value, "sabina_html_price"

    selectors = (
        '[itemprop="price"]',
        '.current-price',
        '.product-current-price',
        '.current_product_price',
        '[class*="current-price"]',
        '[class*="sale-price"]',
    )

    for selector in selectors:
        for node in soup.select(selector):
            classes = " ".join(node.get("class", []))
            marker_text = norm(
                f"{classes} {node.get_text(' ', strip=True)}"
            )

            if any(
                bad in marker_text
                for bad in (
                    "regular price",
                    "old price",
                    "original price",
                    "precio habitual",
                    "precio anterior",
                    "prix habituel",
                    "prix avant",
                    "normalpreis",
                    "streichpreis",
                    "uvp",
                )
            ):
                continue

            raw = (
                node.get("content")
                or node.get("value")
                or node.get_text(" ", strip=True)
            )

            value = money_to_float(raw)
            if value is not None:
                return value, "sabina_html_price"

    # Last fallback: inspect only a product container and only labelled
    # customer-facing prices. Never scan arbitrary EUR amounts on the page.
    containers = soup.select(
        "main, #main, .product-container, .product-information, "
        ".product-detail, .product-page"
    )

    seen = set()
    for container in containers:
        key = id(container)
        if key in seen:
            continue
        seen.add(key)

        text_value = clean(container.get_text(" ", strip=True))

        labelled = re.search(
            r"(?:precio|price|prix|preis)\s*[:\-]\s*"
            r"((?:€|eur|\$|usd|£|gbp)\s*)?"
            r"([0-9][0-9\s.,]*)\s*"
            r"(?:€|eur|\$|usd|£|gbp)?",
            text_value,
            re.I,
        )

        if not labelled:
            continue

        raw = " ".join(
            part for part in (
                labelled.group(1),
                labelled.group(2),
            ) if part
        )
        value = money_to_float(raw)
        if value is not None:
            return value, "sabina_html_price"

    return None, None


def extract_size_ml_from_product_page(soup, title=""):
    """
    Read the selected product size from product-specific fields.

    The whole page is never used as the primary source because related-product
    cards can contain different bottle sizes.
    """
    # Strong structured sources first.
    for selector in (
        '[itemprop="size"]',
        '[itemprop="volume"]',
        '[data-product-size]',
        '[data-size]',
        'input[name*="size" i][checked]',
        'input[name*="size" i][selected]',
        'option[selected]',
    ):
        for node in soup.select(selector):
            raw = (
                node.get("content")
                or node.get("value")
                or node.get("data-product-size")
                or node.get("data-size")
                or node.get_text(" ", strip=True)
            )
            value = extract_size_ml(raw)
            if value is not None:
                return value, "product_page"

    # Product variant / information areas.
    selectors = (
        ".product-variants",
        ".product-attributes",
        ".product-information",
        ".product-detail",
        ".product-actions",
        ".product-combination",
        "[class*='product-variant']",
        "[class*='product-attribute']",
        "[class*='product-size']",
        "[class*='product-volume']",
        "main",
    )

    labels = (
        "tamaño", "tamano", "size", "taille", "grösse", "grosse",
        "größe", "volume", "formato", "ml",
    )

    for selector in selectors:
        for node in soup.select(selector):
            raw = clean(
                node.get_text(" ", strip=True)
            )
            if not raw:
                continue

            normalized = norm(raw)
            if not any(label in normalized for label in labels):
                continue

            value = extract_size_ml(raw)
            if value is not None:
                return value, "product_page"

    # Some product pages put the selected size directly in the title.
    value = extract_size_ml(title)
    if value is not None:
        return value, "product_text"

    return None, None


def availability_from_product_page(soup, jsonld_offer=None):
    """
    Determine availability using product-specific purchase evidence first.

    Priority:
      1. Active product purchase control -> in_stock.
      2. Explicit structured out-of-stock signal -> out_of_stock.
      3. Explicit notification/availability-date block -> out_of_stock.
      4. No reliable evidence -> unknown.

    Generic page text never overrides an active purchase control.
    """
    explicit_in_stock = False
    explicit_out_of_stock = False
    explicit_preorder = False

    if isinstance(jsonld_offer, dict):
        raw = clean(jsonld_offer.get("availability")).lower()
        if "instock" in raw:
            explicit_in_stock = True
        elif any(token in raw for token in ("outofstock", "soldout", "unavailable")):
            explicit_out_of_stock = True
        elif "preorder" in raw:
            explicit_preorder = True

    for selector in (
        '[itemprop="availability"]',
        '[data-availability]',
        '[data-stock-status]',
        '[data-product-availability]',
    ):
        for node in soup.select(selector):
            raw = " ".join(
                str(node.get(attr, ""))
                for attr in (
                    "content", "href", "data-availability",
                    "data-stock-status", "data-product-availability",
                )
            )
            raw = clean(f"{raw} {node.get_text(' ', strip=True)}").lower()
            if "instock" in raw or "in stock" in raw:
                explicit_in_stock = True
            if any(token in raw for token in (
                "outofstock", "out of stock", "soldout", "sold out", "unavailable"
            )):
                explicit_out_of_stock = True

    purchase_roots = soup.select(
        "main, #main, .product-container, .product-information, "
        ".product-detail, .product-page, .product-actions, "
        ".product-add-to-cart, .product-combination, form"
    ) or [soup]

    purchase_words = (
        "añadir al carrito", "agregar al carrito", "comprar",
        "add to cart", "add-to-cart", "buy now",
        "ajouter au panier", "acheter", "in den warenkorb", "jetzt kaufen",
        "acquista", "aggiungi al carrello",
    )
    purchase_markers = (
        "add-to-cart", "add_to_cart", "addtocart", "add-cart",
        "product-add-to-cart", "buy-now", "buy_now", "purchase",
    )

    has_purchase = False
    has_disabled_purchase = False
    seen_nodes = set()

    for root in purchase_roots:
        for node in root.select(
            'button, input[type="submit"], input[type="button"], '
            'a, [data-button-action], [data-action]'
        ):
            node_id = id(node)
            if node_id in seen_nodes:
                continue
            seen_nodes.add(node_id)

            raw = norm(" ".join([
                node.get_text(" ", strip=True),
                node.get("value", ""),
                node.get("aria-label", ""),
                node.get("title", ""),
                " ".join(node.get("class", [])),
                node.get("data-button-action", ""),
                node.get("data-action", ""),
            ]))

            if not any(word in raw for word in purchase_words) and not any(
                marker in raw for marker in purchase_markers
            ):
                continue

            disabled = (
                node.has_attr("disabled")
                or str(node.get("aria-disabled", "")).lower() == "true"
                or "disabled" in node.get("class", [])
            )
            style = norm(node.get("style", ""))
            hidden = (
                node.has_attr("hidden")
                or str(node.get("type", "")).lower() == "hidden"
                or "display none" in style
                or "visibility hidden" in style
            )

            if disabled or hidden:
                has_disabled_purchase = True
            else:
                has_purchase = True

    if has_purchase:
        return "in_stock", "sabina_purchase_control"

    if explicit_in_stock:
        return "in_stock", "sabina_html_availability"

    if has_disabled_purchase or explicit_out_of_stock:
        return "out_of_stock", (
            "sabina_purchase_control" if has_disabled_purchase
            else "sabina_html_availability"
        )

    if explicit_preorder:
        return "preorder", "sabina_jsonld"

    page_text = norm(soup.get_text(" ", strip=True))
    notify_markers = tuple(norm(marker) for marker in (
        "avísame", "avísame cuando esté disponible", "notificarme",
        "notify me", "let me know", "prévenez-moi", "me prévenir",
        "benachrichtigen", "sag mir bescheid",
    ))
    date_markers = tuple(norm(marker) for marker in (
        "fecha de disponibilidad", "availability date",
        "date de disponibilité", "verfügbarkeitsdatum",
    ))

    if any(marker in page_text for marker in notify_markers) and any(
        marker in page_text for marker in date_markers
    ):
        return "out_of_stock", "sabina_notification_block"

    return "unknown", "sabina_html_availability"

SITEMAP_FALLBACK_MAX_INDEXES = 500
SITEMAP_FALLBACK_MAX_URLS_PER_INDEX = 50000


def _catalog_candidate_score(url, query):
    query_norm = norm(query)
    if not query_norm:
        return 0
    path = norm(unquote(urlparse(url).path))
    compact_path = re.sub(r"[^a-z0-9]+", "", path)
    compact_query = re.sub(r"[^a-z0-9]+", "", query_norm)
    if not compact_query or compact_query not in compact_path:
        return 0
    return 100 + len(compact_query)


def _discover_from_sitemaps(session, query):
    """Generic catalog discovery through robots-declared XML sitemaps."""
    sitemap_urls = []
    seen_sitemaps = set()

    def add_sitemap(url):
        absolute = normalise_url(url, BASE_URL)
        if absolute and absolute not in seen_sitemaps:
            seen_sitemaps.add(absolute)
            sitemap_urls.append(absolute)

    try:
        robots = session.get(
            urljoin(BASE_URL, "/robots.txt"),
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if robots.status_code < 400:
            for line in robots.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    add_sitemap(line.split(":", 1)[1].strip())
    except requests.RequestException:
        pass

    if not sitemap_urls:
        add_sitemap(urljoin(BASE_URL, "/sitemap_index_shop_1.xml"))

    queue = list(sitemap_urls)
    candidates = []
    visited = set()

    while queue and len(visited) < SITEMAP_FALLBACK_MAX_INDEXES:
        sitemap = queue.pop(0)
        if sitemap in visited:
            continue
        visited.add(sitemap)
        try:
            response = session.get(
                sitemap,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue
        if response.status_code >= 400:
            continue

        locations = re.findall(
            r"<loc>\s*(.*?)\s*</loc>",
            response.text,
            re.I | re.S,
        )
        for raw in locations[:SITEMAP_FALLBACK_MAX_URLS_PER_INDEX]:
            location = html.unescape(raw.strip())
            if location.lower().endswith((".xml", ".xml.gz")):
                add_sitemap(location)
                if location not in visited and location not in queue:
                    queue.append(location)
                continue
            absolute = normalise_url(location, sitemap)
            if not absolute or not is_product_url(absolute):
                continue
            score = _catalog_candidate_score(absolute, query)
            if score:
                candidates.append((score, absolute))

        if candidates:
            candidates.sort(key=lambda item: (-item[0], item[1]))
            return [url for _, url in candidates[:MAX_CANDIDATES]]

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [url for _, url in candidates[:MAX_CANDIDATES]]


CATALOG_FALLBACK_MAX_SEEDS = 2
CATALOG_FALLBACK_MAX_PAGES_PER_SEED = 24
CATALOG_FALLBACK_WORKERS = 12
CATALOG_BRAND_INDEX_URL = "/es/marcas"


def _catalog_query_matches(text, query):
    tokens = query_tokens(query)
    normalized = norm(text)
    return bool(tokens) and all(token in normalized for token in tokens)


def _catalog_product_urls_from_page(soup, query, base_url):
    """Extract product URLs only when the product card itself matches query."""
    urls = []
    seen = set()
    query_compact = re.sub(r"[^a-z0-9]+", "", norm(query))

    for anchor in soup.find_all("a", href=True):
        absolute = normalise_url(anchor.get("href"), base_url)
        if not absolute or not is_product_url(absolute) or absolute in seen:
            continue

        anchor_text = clean(anchor.get_text(" ", strip=True))
        card = anchor
        for _ in range(5):
            parent = getattr(card, "parent", None)
            if not parent:
                break
            parent_text = clean(parent.get_text(" ", strip=True))
            if len(parent_text) > len(anchor_text):
                anchor_text = parent_text
            card = parent
            if len(parent_text) >= 80:
                break

        path_compact = re.sub(
            r"[^a-z0-9]+", "",
            norm(unquote(urlparse(absolute).path)),
        )

        if (query_compact and query_compact in path_compact) or _catalog_query_matches(anchor_text, query):
            seen.add(absolute)
            urls.append(absolute)

    return urls


def _catalog_brand_urls_from_index(soup, base_url):
    """Discover brand landing pages from Sabina's live brand index."""
    urls = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        absolute = normalise_url(anchor.get("href"), base_url)
        if not absolute or is_product_url(absolute) or absolute in seen:
            continue
        parsed = urlparse(absolute)
        if parsed.netloc.lower() not in {"sabina.com", "www.sabina.com"}:
            continue
        path = parsed.path.rstrip("/")
        if not path or path in {"", "/es", "/es/marcas"}:
            continue
        # Brand links on this surface are numeric-slug paths such as /es/579_afnan.
        if not re.match(r"^/es/\d+_[^/]+$", path, re.I):
            continue
        seen.add(absolute)
        urls.append(absolute)
    return urls


def _fetch_catalog_page(session, page_url):
    try:
        response = session.get(
            page_url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None
    if response.status_code >= 400:
        return None
    return response


def _discover_from_brand_index(session, query):
    """Search Sabina's generic live brand index before crawling broad categories."""
    response = _fetch_catalog_page(
        session,
        urljoin(BASE_URL, CATALOG_BRAND_INDEX_URL),
    )
    if response is None:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    brand_urls = _catalog_brand_urls_from_index(soup, response.url)
    if not brand_urls:
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    # Preserve the retailer's brand-index order. Process small concurrent
    # batches so a matching brand can terminate discovery quickly without
    # crawling the whole catalog. No brand/product is hard-coded.
    batch_size = CATALOG_FALLBACK_WORKERS
    for offset in range(0, len(brand_urls), batch_size):
        batch = brand_urls[offset:offset + batch_size]
        found = []
        seen_products = set()
        with ThreadPoolExecutor(max_workers=CATALOG_FALLBACK_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_catalog_page, session, url): url
                for url in batch
            }
            for future in as_completed(futures):
                page_response = future.result()
                if page_response is None:
                    continue
                page_soup = BeautifulSoup(page_response.text, "html.parser")
                for product_url in _catalog_product_urls_from_page(
                    page_soup,
                    query,
                    page_response.url,
                ):
                    if product_url in seen_products:
                        continue
                    seen_products.add(product_url)
                    found.append(product_url)
                    if len(found) >= MAX_CANDIDATES:
                        return found[:MAX_CANDIDATES]
        if found:
            return found[:MAX_CANDIDATES]

    return []


def _catalog_seed_urls_from_homepage(soup, base_url):
    """Discover retailer category/brand landing pages from the live homepage."""
    seeds = []
    seen = set()
    priority_words = (
        "perfume", "perfumes", "parfum", "fragrance", "fragrances",
        "cosmetic", "cosmetica", "makeup", "maquillaje", "beauty",
        "care", "skincare", "cabello", "hair", "body", "hombre", "mujer",
    )

    candidates = []
    for anchor in soup.find_all("a", href=True):
        absolute = normalise_url(anchor.get("href"), base_url)
        if not absolute or is_product_url(absolute):
            continue
        parsed = urlparse(absolute)
        if parsed.netloc.lower() not in {"sabina.com", "www.sabina.com"}:
            continue
        path = parsed.path.rstrip("/")
        if not path or path in {"", "/es", "/es/"} or "." in path.rsplit("/", 1)[-1]:
            continue
        text = clean(anchor.get_text(" ", strip=True))
        normalized = norm(f"{text} {path}")
        score = sum(10 for word in priority_words if word in normalized)
        numeric_category = bool(re.search(r"/es/(?:\d+-|\d+_)", path, re.I))
        perfume_surface = any(
            word in normalized
            for word in ("perfume", "perfumes", "parfum", "fragrance", "fragancias")
        )
        if numeric_category:
            score += 5
        if numeric_category and perfume_surface:
            score += 100
        elif not perfume_surface:
            continue
        candidates.append((score, absolute))

    for _, url in sorted(candidates, key=lambda item: (-item[0], item[1])):
        if url in seen:
            continue
        seen.add(url)
        seeds.append(url)
        if len(seeds) >= CATALOG_FALLBACK_MAX_SEEDS:
            break
    return seeds


def _catalog_page_urls(seed, max_pages):
    """Generate the retailer's observed generic pagination form (?p=N)."""
    parsed = urlparse(seed)
    base = parsed._replace(query="", fragment="")
    root = base.geturl()
    return [root if page == 1 else root + "?p=" + str(page) for page in range(1, max_pages + 1)]


def _discover_from_catalog_pages(session, query):
    """Generic catalog fallback for stores whose product sitemap is empty."""
    brand_found = _discover_from_brand_index(session, query)
    if brand_found:
        return brand_found[:MAX_CANDIDATES]

    try:
        response = session.get(
            urljoin(BASE_URL, "/es/"),
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return []

    if response.status_code >= 400:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    seeds = _catalog_seed_urls_from_homepage(soup, response.url)
    if not seeds:
        return []

    from concurrent.futures import ThreadPoolExecutor, as_completed

    for seed in seeds:
        page_urls = _catalog_page_urls(seed, CATALOG_FALLBACK_MAX_PAGES_PER_SEED)
        found = []
        seen_products = set()

        with ThreadPoolExecutor(max_workers=CATALOG_FALLBACK_WORKERS) as executor:
            futures = {
                executor.submit(_fetch_catalog_page, session, url): url
                for url in page_urls
            }
            for future in as_completed(futures):
                page_response = future.result()
                if page_response is None:
                    continue
                page_soup = BeautifulSoup(page_response.text, "html.parser")
                for product_url in _catalog_product_urls_from_page(
                    page_soup, query, page_response.url
                ):
                    if product_url in seen_products:
                        continue
                    seen_products.add(product_url)
                    found.append(product_url)
                    if len(found) >= MAX_CANDIDATES:
                        for pending in futures:
                            if not pending.done():
                                pending.cancel()
                        return found[:MAX_CANDIDATES]

        if found:
            return found[:MAX_CANDIDATES]

    return []

def discover_product_urls(session, query):
    """
    Discover product URLs through Sabina's normal search surface.

    If the search surface returns only unrelated template/recommendation links,
    verify the catalog generically through the retailer's live category
    pagination. No product, brand, SKU, price or URL is hard-coded.
    """
    try:
        response = session.get(
            SEARCH_URL,
            params={"search_query": query},
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return []

    if response.status_code >= 400:
        return []

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    urls = []
    seen = set()
    query_compact = re.sub(r"[^a-z0-9]+", "", norm(query))

    def add(raw):
        absolute = normalise_url(raw, response.url)
        if not absolute or not is_product_url(absolute):
            return

        path_compact = re.sub(
            r"[^a-z0-9]+",
            "",
            norm(unquote(urlparse(absolute).path)),
        )
        if not query_compact or query_compact not in path_compact:
            return
        if absolute in seen:
            return
        seen.add(absolute)
        urls.append(absolute)

    for anchor in soup.find_all("a", href=True):
        add(anchor.get("href"))

    decoded = (
        response.text
        .replace("\\/", "/")
        .replace("\\u002F", "/")
    )

    for match in re.finditer(
        r'https?://(?:www\.)?sabina\.com/'
        r'(?:es|it|fr|en|de|nl|pt)/'
        r'[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(match.group(0))

    for match in re.finditer(
        r'/(?:es|it|fr|en|de|nl|pt)/'
        r'[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(match.group(0))

    if urls:
        return urls[:MAX_CANDIDATES]

    return _discover_from_catalog_pages(session, query)

def _offer_list(product):
    offers = product.get("offers") if isinstance(product, dict) else None
    if isinstance(offers, dict):
        return [offers]
    if isinstance(offers, list):
        return [offer for offer in offers if isinstance(offer, dict)]
    return []


def _offer_size(offer, product):
    parts = []
    for value in (
        offer.get("name"),
        offer.get("description"),
        offer.get("sku"),
        offer.get("url"),
        product.get("name"),
        product.get("description"),
        product.get("sku"),
    ):
        if value:
            parts.append(str(value))
    return extract_size_ml(" ".join(parts))


def _select_product_offer(product, final_url, title, size_ml):
    offers = _offer_list(product)

    if not offers:
        return None

    # Bind the offer to the exact product page/name whenever possible.
    same_product = []
    for offer in offers:
        offer_url = normalise_url(offer.get("url"))
        offer_name = clean(offer.get("name"))

        if offer_url == final_url:
            same_product.append(offer)
        elif offer_name and (
            query_matches(offer_name, title)
            or query_matches(title, offer_name)
        ):
            same_product.append(offer)

    # Never guess between multiple unrelated offers.
    candidates = same_product if same_product else (
        offers if len(offers) == 1 else []
    )

    if not candidates:
        return None

    # If the offer itself declares a bottle size, it must match the
    # selected product size. Never take an unrelated variant's price.
    if size_ml is not None:
        sized = [
            offer for offer in candidates
            if _offer_size(offer, product) is not None
            and abs(_offer_size(offer, product) - size_ml) < 0.01
        ]
        if sized:
            candidates = sized
        elif any(
            _offer_size(offer, product) is not None
            for offer in candidates
        ):
            return None

    priced = [
        offer for offer in candidates
        if money_to_float(offer.get("price")) is not None
    ]

    return priced[0] if priced else candidates[0]


def extract_product_page(session, url, query):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if response.status_code >= 400:
        return None

    final_url = normalise_url(response.url)

    if not final_url or not is_product_url(final_url):
        return None

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    h1 = soup.select_one("h1")
    h1_text = (
        clean(h1.get_text(" ", strip=True))
        if h1
        else ""
    )

    product = first_jsonld_product(
        soup,
        expected_url=final_url,
        expected_title=h1_text or None,
    )

    title = clean(
        (product or {}).get("name")
        or h1_text
    )

    if not title:
        return None

    brand = None
    raw_brand = (product or {}).get("brand")

    if isinstance(raw_brand, dict):
        brand = clean(raw_brand.get("name")) or None
    elif raw_brand:
        brand = clean(raw_brand)

    if not query_matches(
        f"{title} {brand or ''}",
        query,
    ):
        return None

    # Determine the product size from product-specific areas first.
    size_ml, size_source = extract_size_ml_from_product_page(
        soup,
        title,
    )

    # Select price from the offer belonging to this exact product/format.
    offer = _select_product_offer(
        product or {},
        final_url,
        title,
        size_ml,
    )

    price = (
        money_to_float(offer.get("price"))
        if isinstance(offer, dict)
        else None
    )
    price_source = "sabina_jsonld"

    # If JSON-LD has no usable price, use the product-page HTML fallback.
    # This fallback deliberately ignores struck-through/reference prices.
    if price is None:
        price, price_source = extract_price_from_html(soup)

    currency = (
        clean(offer.get("priceCurrency"))
        if isinstance(offer, dict)
        else ""
    ) or "EUR"

    availability, availability_source = availability_from_product_page(
        soup,
        offer,
    )

    image = (product or {}).get("image")

    if isinstance(image, list):
        image = image[0] if image else None

    if isinstance(image, dict):
        image = (
            image.get("url")
            or image.get("contentUrl")
        )

    if image:
        image = urljoin(
            response.url,
            image,
        )

    gtin = clean(
        (product or {}).get("gtin13")
        or (product or {}).get("gtin12")
        or (product or {}).get("gtin14")
        or (product or {}).get("gtin")
    ) or None

    mpn = clean(
        (product or {}).get("mpn")
    ) or None

    sku = clean(
        (product or {}).get("sku")
    ) or None

    page_text = soup.get_text(
        " ",
        strip=True,
    )

    if not sku:
        reference_match = re.search(
            r"(?:referencia|reference|référence|riferimento)"
            r"\s*[:#]?\s*([A-Z0-9_-]+)",
            page_text,
            re.I,
        )

        if reference_match:
            sku = reference_match.group(1)

    product_id = product_id_from_url(
        final_url
    )

    concentration, concentration_source = (
        extract_concentration(
            title,
            page_text,
        )
    )

    gender, gender_source = extract_gender(
        title,
        page_text,
    )

    return {
        "store": STORE,

        "source": {
            "url": final_url,
            "name": title,
            "brand": brand,
            "image": image,
        },

        "identity": {
            "gtin": (
                {
                    "value": gtin,
                    "source": "sabina_jsonld",
                }
                if gtin
                else None
            ),

            "mpn": (
                {
                    "value": mpn,
                    "source": "sabina_jsonld",
                }
                if mpn
                else None
            ),

            "sku": (
                {
                    "value": sku,
                    "source": "sabina_jsonld_or_reference",
                }
                if sku
                else None
            ),

            "store_product_id": (
                {
                    "value": product_id,
                    "source": "product_url",
                }
                if product_id
                else None
            ),
        },

        "attributes": {
            "size_ml": (
                {
                    "value": size_ml,
                    "source": size_source,
                }
                if size_ml is not None
                else None
            ),

            "concentration": (
                {
                    "value": concentration,
                    "source": concentration_source,
                }
                if concentration
                else None
            ),

            "gender": (
                {
                    "value": gender,
                    "source": gender_source,
                }
                if gender_source
                else {
                    "value": "unknown",
                    "source": "default",
                }
            ),

            "packaging_type": {
                "value": "product",
                "source": "default",
            },
        },

        "offer": {
            "price": price,
            "currency": currency,
            "availability": availability,
        },

        "provenance": {
            "name": "sabina_jsonld_or_h1",
            "brand": (
                "sabina_jsonld"
                if brand
                else None
            ),
            "price": price_source,
            "availability": availability_source,
            "image": (
                "sabina_jsonld"
                if image
                else None
            ),
            "store_product_id": (
                "product_url"
                if product_id
                else None
            ),
            "sku": (
                "sabina_jsonld_or_reference"
                if sku
                else None
            ),
            "gtin": (
                "sabina_jsonld"
                if gtin
                else None
            ),
            "mpn": (
                "sabina_jsonld"
                if mpn
                else None
            ),
            "size_ml": size_source,
            "concentration": concentration_source,
            "gender": gender_source,
            "packaging_type": "default",
        },

        "raw_data": {
            "product_url": final_url,
            "status_code": response.status_code,
            "jsonld_product": product,
        },

        "name": title,
        "brand": brand,
        "price": (
            f"{price:.2f}".replace(".", ",")
            + " €"
            if price is not None
            else ""
        ),
        "url": final_url,
        # Unknown is intentionally not converted to false.
        # The main backend must not interpret missing evidence as OOS.
        "available": (
            True if availability == "in_stock"
            else False if availability == "out_of_stock"
            else None
        ),
    }

def _fallback_extract_product_page(session, url, query):
    """Minimal product-page parser used only when the rich parser raises.

    It is deliberately generic: it reads the current product H1, visible
    customer price, size and purchase/notification state from the retailer
    page. It never contains a product-specific URL or price.
    """
    try:
        response = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
    except requests.RequestException:
        return None

    try:
        if response.status_code >= 400:
            return None
        final_url = normalise_url(response.url)
        if not final_url or not is_product_url(final_url):
            return None
        soup = BeautifulSoup(response.text, "html.parser")
    finally:
        response.close()

    h1 = soup.select_one("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else ""
    if not title or not query_matches(title, query):
        return None

    page_text = clean(soup.get_text(" ", strip=True))

    # Prefer the visible customer-facing price near the product heading.
    price = None
    price_patterns = (
        r"precio\s*:\s*([0-9][0-9\s.,]*)\s*€",
        r"price\s*:\s*([0-9][0-9\s.,]*)\s*€",
        r"([0-9]{1,4}(?:[.,][0-9]{1,2})?)\s*€\s*\([^)]*100ml",
    )
    for pattern in price_patterns:
        match = re.search(pattern, page_text, re.I)
        if match:
            candidate = money_to_float(match.group(1))
            if candidate is not None and candidate > 0:
                price = candidate
                break

    size = extract_size_ml(title, page_text)
    normalized = norm(page_text)
    if any(marker in normalized for marker in ("fecha de disponibilidad", "avísame", "notificarme", "notify me")):
        availability = "out_of_stock"
    elif any(marker in normalized for marker in ("añadir al carrito", "agregar al carrito", "comprar", "add to cart", "buy now")):
        availability = "in_stock"
    else:
        availability = "unknown"

    image = None
    meta = soup.select_one('meta[property="og:image"]')
    if meta and meta.get("content"):
        image = urljoin(BASE_URL, meta.get("content"))

    return {
        "store": STORE,
        "source": {"url": final_url, "name": title, "brand": None, "image": image},
        "identity": {"gtin": None, "mpn": None, "sku": None, "store_product_id": {"value": product_id_from_url(final_url), "source": "product_url"}, "store_variant_id": None},
        "attributes": {"size_ml": {"value": size, "source": "product_page"} if size is not None else None, "concentration": {"value": extract_concentration(title, page_text)[0], "source": "product_text"} if extract_concentration(title, page_text)[0] else None, "gender": {"value": "unknown", "source": "default"}, "packaging_type": {"value": "product", "source": "default"}},
        "offer": {"price": price, "currency": "EUR", "availability": availability},
        "provenance": {"name": "sabina_html_fallback", "price": "visible_product_page", "availability": "visible_product_page", "size_ml": "visible_product_page"},
        "raw_data": {"product_url": final_url, "status_code": 200},
        "name": title,
        "brand": None,
        "price": f"{price:.2f}".replace(".", ",") + " €" if price is not None else "",
        "price_num": price,
        "url": final_url,
        "available": True if availability == "in_stock" else False if availability == "out_of_stock" else None,
        "availability": availability,
        "size_ml": size,
        "image": image,
    }


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()

    try:
        candidate_urls = discover_product_urls(
            session,
            query,
        )

        results = []
        seen = set()

        for url in candidate_urls:
            try:
                product = extract_product_page(
                    session,
                    url,
                    query,
                )
            except Exception:
                product = None

            if not product:
                try:
                    product = _fallback_extract_product_page(
                        session,
                        url,
                        query,
                    )
                except Exception:
                    product = None

            if not product:
                continue

            product_id = (
                product.get("identity", {})
                .get("store_product_id", {})
                .get("value")
            )

            key = product_id or product.get("url")

            if key in seen:
                continue

            seen.add(key)
            results.append(product)

        return results

    finally:
        session.close()


def search_stream(query, emit=None):
    """
    Return the common ScentHunter scraper contract.

    When a callback is supplied, rows are emitted exactly as before, but the
    function ALSO returns the structured report required by the current
    backend contract. Returning None here is a contract violation because
    the backend uses the return value to classify the store result.
    """
    query = clean(query)

    if not query:
        report = {
            "status": "success",
            "verified": True,
            "results": [],
            "error": None,
            "details": {"reason": "empty_query", "count": 0},
        }
        return report

    try:
        rows = search(query)
    except requests.Timeout as exc:
        return {
            "status": "timeout",
            "verified": False,
            "results": [],
            "error": str(exc),
            "details": {"exception": type(exc).__name__},
        }
    except requests.ConnectionError as exc:
        return {
            "status": "unavailable",
            "verified": False,
            "results": [],
            "error": str(exc),
            "details": {"exception": type(exc).__name__},
        }
    except requests.RequestException as exc:
        return {
            "status": "error",
            "verified": False,
            "results": [],
            "error": str(exc),
            "details": {"exception": type(exc).__name__},
        }
    except Exception as exc:
        return {
            "status": "error",
            "verified": False,
            "results": [],
            "error": str(exc),
            "details": {"exception": type(exc).__name__},
        }

    if callable(emit):
        for row in rows:
            emit(row)

    if rows:
        return {
            "status": "success",
            "verified": True,
            "results": rows,
            "error": None,
            "details": {"count": len(rows)},
        }

    # The existing discovery function returns [] both for a genuinely empty
    # search and for some technical discovery failures. Therefore an empty
    # result is NOT claimed as verified NOT_FOUND here.
    return {
        "status": "partial",
        "verified": False,
        "results": [],
        "error": None,
        "details": {
            "count": 0,
            "reason": "empty_search_not_authoritatively_verified",
        },
    }


# Compatibility with the generic main.py interface.
scrape = search


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Generic Sabina scraper"
    )
    parser.add_argument(
        "query",
        help="Search query supplied at runtime",
    )

    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
