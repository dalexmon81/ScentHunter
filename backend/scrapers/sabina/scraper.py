import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
SEARCH_URL = BASE_URL + "/es/buscar"
SITEMAP_INDEX_URL = BASE_URL + "/sitemap_index_shop_1.xml"
TIMEOUT = 10
MAX_CANDIDATES = 30
MAX_SITEMAPS = 30

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
        if token not in IGNORED_QUERY_WORDS and not token.isdigit()
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


def first_jsonld_product(soup):
    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
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
            types = (
                item_type
                if isinstance(item_type, list)
                else [item_type]
            )

            if any(
                str(item_type_value).lower() == "product"
                for item_type_value in types
            ):
                return item

    return None



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
    Generic fallback for pages where Sabina does not expose Product JSON-LD.

    Priority:
    1. Product price metadata / itemprop.
    2. Current-price DOM elements.
    3. Visible product-price text.

    Deliberately avoids "regular/old/original price" labels so a struck-through
    reference price is never selected as the live offer price.
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

    for selector in (
        '[itemprop="price"]',
        '.current-price',
        '.product-price',
        '.current_product_price',
        '.product-current-price',
        '[class*="current-price"]',
        '[class*="product-price"]',
        '[class*="sale-price"]',
    ):
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

    # Last fallback: inspect only the main product area, not related products.
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

        text_value = clean(
            container.get_text(" ", strip=True)
        )

        # A labelled current price is safest when it has a separator.
        labelled = re.search(
            r"(?:precio|price|prix|preis)\s*[:\-]\s*"
            r"((?:€|eur|\$|usd|£|gbp)\s*)?"
            r"([0-9][0-9\s.,]*)\s*"
            r"(?:€|eur|\$|usd|£|gbp)?",
            text_value,
            re.I,
        )

        if labelled:
            raw = " ".join(
                part
                for part in (
                    labelled.group(1),
                    labelled.group(2),
                )
                if part
            )
            value = money_to_float(raw)
            if value is not None:
                return value, "sabina_html_price"

        # Otherwise inspect every currency amount and reject amounts that are
        # explicitly described as regular/old/original/reference prices.
        amount_re = re.compile(
            r"(?:(€|eur|\$|usd|£|gbp)\s*)?"
            r"([0-9][0-9\s.,]*)\s*"
            r"(€|eur|\$|usd|£|gbp)?",
            re.I,
        )

        for match in amount_re.finditer(text_value):
            context = norm(
                text_value[
                    max(0, match.start() - 60):match.start()
                ]
            )

            if any(
                marker in context
                for marker in (
                    "precio habitual",
                    "precio anterior",
                    "precio original",
                    "regular price",
                    "old price",
                    "original price",
                    "prix habituel",
                    "prix avant",
                    "normalpreis",
                    "streichpreis",
                    "uvp",
                )
            ):
                continue

            raw = " ".join(
                part
                for part in (
                    match.group(1),
                    match.group(2),
                    match.group(3),
                )
                if part
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

def _add_product_url(urls, seen, raw, base_url=BASE_URL):
    absolute = normalise_url(raw, base_url)
    if not absolute or not is_product_url(absolute):
        return False
    if absolute in seen:
        return False
    seen.add(absolute)
    urls.append(absolute)
    return True


def _discover_product_urls_from_search(session, query):
    """Discover product URLs through Sabina's live search page."""
    response = session.get(
        SEARCH_URL,
        params={"search_query": query},
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )

    if response.status_code >= 400:
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    urls = []
    seen = set()

    def add(raw):
        _add_product_url(urls, seen, raw, response.url)

    for anchor in soup.find_all("a", href=True):
        add(anchor.get("href"))

    decoded = (
        response.text
        .replace("\\/", "/")
        .replace("\\u002F", "/")
    )

    for match in re.finditer(
        r'https?://(?:www\\.)?sabina\\.com/'
        r'(?:es|it|fr|en|de|nl|pt)/[^"\'<>\\s\\\\]+',
        decoded,
        re.I,
    ):
        add(match.group(0))

    for match in re.finditer(
        r'/(?:es|it|fr|en|de|nl|pt)/[^"\'<>\\s\\\\]+',
        decoded,
        re.I,
    ):
        add(match.group(0))

    return urls


def _discover_product_urls_from_sitemaps(session, query):
    """
    Generic catalog discovery fallback.

    Sabina is PrestaShop and publishes a sitemap index in robots.txt. The
    product sitemap URLs contain the same canonical product URLs used by
    product pages. We therefore use the store's own sitemap as a catalog
    source instead of adding product-, brand- or SKU-specific rules.
    """
    response = session.get(
        SITEMAP_INDEX_URL,
        headers=HEADERS,
        timeout=TIMEOUT,
        allow_redirects=True,
    )
    if response.status_code >= 400:
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "xml")
    sitemap_urls = []
    seen_sitemaps = set()

    for loc in soup.find_all("loc"):
        raw = clean(loc.get_text())
        absolute = normalise_url(raw, response.url)
        if not absolute or absolute in seen_sitemaps:
            continue
        seen_sitemaps.add(absolute)
        sitemap_urls.append(absolute)
        if len(sitemap_urls) >= MAX_SITEMAPS:
            break

    if not sitemap_urls:
        # Some sitemap indexes can be returned as HTML/plain XML despite
        # content-type quirks. Keep discovery generic by extracting locs.
        for match in re.finditer(
            r'<loc>\s*(https?://[^<\s]+)\s*</loc>',
            response.text,
            re.I,
        ):
            absolute = normalise_url(match.group(1), response.url)
            if absolute and absolute not in seen_sitemaps:
                seen_sitemaps.add(absolute)
                sitemap_urls.append(absolute)
                if len(sitemap_urls) >= MAX_SITEMAPS:
                    break

    tokens = query_tokens(query)
    if not tokens:
        return []

    urls = []
    seen_products = set()

    for sitemap_url in sitemap_urls:
        child = session.get(
            sitemap_url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        if child.status_code >= 400:
            child.raise_for_status()

        # Product sitemap files are XML, but using regex here also tolerates
        # servers that send an unexpected content-type.
        locs = re.findall(
            r'<loc>\s*(https?://[^<\s]+)\s*</loc>',
            child.text,
            re.I,
        )
        if not locs:
            child_soup = BeautifulSoup(child.text, "xml")
            locs = [clean(loc.get_text()) for loc in child_soup.find_all("loc")]

        for raw in locs:
            product_url = normalise_url(raw, child.url)
            if not is_product_url(product_url):
                continue

            # Discovery is lexical only. Identity, size and concentration are
            # deliberately left to normalization + ProductMatcher.
            path_text = norm(urlparse(product_url).path)
            if not all(token in path_text for token in tokens):
                continue

            if _add_product_url(urls, seen_products, product_url, child.url):
                if len(urls) >= MAX_CANDIDATES:
                    return urls

    return urls


def discover_product_urls(session, query):
    """
    Generic first-party discovery.

    Restored from the verified 20-Sep Sabina strategy: the storefront exposed
    several equivalent search routes, so discovery must not depend on only
    one endpoint. No product/family/brand-specific URL is used here.
    """
    urls = []
    seen = set()

    q = quote_plus(query)

    search_urls = (
        SEARCH_URL + "?s=" + q,
        SEARCH_URL + "?controller=search&s=" + q,
        BASE_URL + "/es/buscar_old?s=" + q,
        SEARCH_URL + "?search_query=" + q,
        BASE_URL + "/es/buscar_old?search_query=" + q,
        BASE_URL + "/es/search?s=" + q,
    )

    def add_links(html):
        links = []
        soup = BeautifulSoup(html or "", "html.parser")

        for anchor in soup.find_all("a", href=True):
            href = anchor.get("href") or ""
            absolute = _clean_product_url(href)
            if not absolute or absolute in seen:
                continue

            name = _clean(anchor.get_text(" ", strip=True))
            title = _clean(anchor.get("title") or "")
            if not query_matches(f"{name} {title}", absolute, query):
                continue

            seen.add(absolute)
            urls.append(absolute)
            links.append(absolute)

            if len(urls) >= MAX_CANDIDATES:
                break

        return links

    # Try every generic first-party search route until one actually produces
    # candidates. This is the key difference from the broken single-route
    # discovery.
    for url in search_urls:
        try:
            response = session.get(
                url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.Timeout:
            continue
        except requests.RequestException:
            continue

        try:
            if response.status_code >= 400:
                continue
            links = add_links(response.text)
        finally:
            response.close()

        if len(urls) >= MAX_CANDIDATES or links:
            break

    # Sitemap discovery remains generic and is useful when the storefront
    # search does not expose a newly indexed product.
    if len(urls) < MAX_CANDIDATES:
        try:
            for link in _discover_product_urls_from_sitemaps(
                session,
                query,
            ):
                if link not in seen:
                    seen.add(link)
                    urls.append(link)
                    if len(urls) >= MAX_CANDIDATES:
                        break
        except Exception:
            pass

    # Historical generic AJAX fallback. It only discovers URLs; it does not
    # assign identity, family, variant, or canonical format.
    if len(urls) < MAX_CANDIDATES:
        ajax_endpoints = (
            BASE_URL + "/es/module/ec_customization/ajax",
            BASE_URL + "/es/modules/ec_customization/ajax",
            BASE_URL + "/modules/ecelastic/ajax.php",
        )

        payloads = (
            {"s": query, "query": query, "search_query": query},
            {"q": query, "query": query, "search_query": query},
        )

        for endpoint in ajax_endpoints:
            for payload in payloads:
                try:
                    response = session.get(
                        endpoint,
                        params=payload,
                        headers={
                            **HEADERS,
                            "X-Requested-With": "XMLHttpRequest",
                        },
                        timeout=TIMEOUT,
                        allow_redirects=True,
                    )
                except requests.RequestException:
                    continue

                try:
                    if response.status_code >= 400:
                        continue
                    links = add_links(response.text)
                finally:
                    response.close()

                if len(urls) >= MAX_CANDIDATES:
                    break
            if len(urls) >= MAX_CANDIDATES:
                break

    return urls[:MAX_CANDIDATES]



def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Warm-up keeps the same session/cookies used for discovery and fetch.
        try:
            response = session.get(
                BASE_URL + "/es/",
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            response.close()
        except requests.RequestException:
            pass

        candidate_urls = discover_product_urls(
            session,
            query,
        )

        results = []
        seen = set()

        # Keep the historical bounded parallel extraction model.
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if candidate_urls:
            with ThreadPoolExecutor(
                max_workers=min(8, len(candidate_urls))
            ) as pool:
                futures = {
                    pool.submit(
                        extract_product_page,
                        session,
                        url,
                        query,
                    ): url
                    for url in candidate_urls
                }

                for future in as_completed(futures):
                    try:
                        rows = future.result()
                    except Exception:
                        continue

                    if not rows:
                        continue

                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        key = (
                            row.get("store_product_id")
                            or row.get("url")
                        )
                        key = (
                            key,
                            row.get("size_ml"),
                            row.get("price_num"),
                            row.get("availability"),
                        )
                        if key in seen:
                            continue
                        seen.add(key)
                        results.append(row)

        return results[:80]

    finally:
        session.close()


def search_stream(query, emit=None):
    """
    Common ScentHunter scraper contract.

    Empty results are PARTIAL/unverified, never verified NOT_FOUND.
    """
    try:
        rows = search(query)

        if callable(emit):
            for row in rows:
                emit(row)

        if rows:
            return {
                "status": "success",
                "verified": True,
                "results": [] if callable(emit) else rows,
                "error": None,
                "details": {
                    "discovery": "20sep_first_party_search_routes"
                },
            }

        return {
            "status": "partial",
            "verified": False,
            "results": [],
            "error": None,
            "details": {
                "reason": "empty_search_not_authoritatively_verified",
                "discovery": "20sep_first_party_search_routes",
            },
        }

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


def scrape(query):
    return search_stream(query)



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
