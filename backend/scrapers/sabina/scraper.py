import json
import re
import unicodedata
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
# Generic native-search endpoints. No product/brand-specific routes.
SEARCH_ENDPOINTS = (
    (BASE_URL + "/es/buscar", {"search_query": True}),
    (BASE_URL + "/it/ricerca", {"s": True}),
    (BASE_URL + "/it/search", {"s": True}),
)
TIMEOUT = 7
DISCOVERY_TIMEOUT = 7
PRODUCT_WORKERS = 6
MAX_CANDIDATES = 40
MAX_SITEMAP_CANDIDATES = 40
# Bounded browser fallback for Sabina's generic native search.
BROWSER_DISCOVERY_TIMEOUT_MS = 15000
BROWSER_DISCOVERY_WAIT_MS = 1000

# Sabina's Italian generic search is powered by Sellboost.
SELLBOOST_SEARCH_URL = "https://api.sellboost.com/finder/search"
SELLBOOST_SHOP_ID = "fd08e30c-8347-4a9f-ae40-94463e3d1e59"
SELLBOOST_SUB_SHOP_ID = "shop|1"
SELLBOOST_COUNTRY = "IT"
SELLBOOST_COUNTRY_ID = 10
SELLBOOST_LANGUAGE = "it"
SELLBOOST_CURRENCY = "EUR"
SELLBOOST_REGISTERS_PER_PAGE = 50
SELLBOOST_MAX_PAGES = 10

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
    r"^/(?:es|it|fr|en|de|nl|pt|tw|da|pl)/[^/]+/(\d+)-[^/]+\.html$",
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
            # Schema.org types may be plain names or full URI values.
            # Accept Product, https://schema.org/Product and equivalent URI forms.
            is_product = any(
                isinstance(value, str)
                and re.split(r"[/#]", value.strip().rstrip("/"))[-1].lower() == "product"
                for value in types
            )
            if not is_product:
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
                else:
                    # Product-page H1 and JSON-LD names often differ only by
                    # retailer-added brand words or omitted generic wording.
                    # Score shared meaningful tokens without requiring every
                    # H1 token to occur in the structured product name.
                    title_tokens = set(query_tokens(expected_title))
                    name_tokens = set(query_tokens(item_name))
                    if title_tokens and name_tokens:
                        overlap = len(title_tokens & name_tokens)
                        coverage = overlap / min(len(title_tokens), len(name_tokens))
                        if overlap >= 2 and coverage >= 0.5:
                            score += 30

            if item.get("offers"):
                score += 5

            candidates.append((score, item))

    if not candidates:
        return None

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    score, product = candidates[0]

    if (expected_path or expected_title_norm) and score < 30:
        # When the page contains exactly one Product JSON-LD object, allow a
        # modest title mismatch only if the structured name shares meaningful
        # tokens with the visible H1. Never use this fallback when multiple
        # Product objects could represent related/recommended products.
        if len(candidates) != 1 or not expected_title_norm:
            return None
        product_name = norm(candidates[0][1].get("name", ""))
        title_tokens = set(query_tokens(expected_title))
        name_tokens = set(query_tokens(product_name))
        overlap = len(title_tokens & name_tokens)
        if not title_tokens or not name_tokens or overlap < 2:
            return None
        if overlap / min(len(title_tokens), len(name_tokens)) < 0.5:
            return None
        product = candidates[0][1]

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
            r"(?:prezzo|precio|price|prix|preis)\s*[:\-]\s*"
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

def _candidate_score(url, anchor_text, query):
    """Generic relevance score; never contains product-specific rules."""
    tokens = query_tokens(query)
    text = norm(f"{anchor_text or ''} {url or ''}")
    if not tokens:
        return 0

    matched = sum(1 for token in tokens if token in text)
    score = matched * 10
    if all(token in text for token in tokens):
        score += 25
    return score


def _extract_search_candidates(response, query):
    """Extract product URLs and rank them using only runtime query text."""
    soup = BeautifulSoup(response.text, "html.parser")
    ranked = {}

    def add(raw, context=""):
        absolute = normalise_url(raw, response.url)
        if not absolute or not is_product_url(absolute):
            return
        score = _candidate_score(absolute, context, query)
        previous = ranked.get(absolute)
        if previous is None or score > previous:
            ranked[absolute] = score

    for anchor in soup.find_all("a", href=True):
        label = clean(anchor.get_text(" ", strip=True))
        context = label
        parent = anchor.parent
        if parent:
            context = clean(parent.get_text(" ", strip=True))[:500]
        add(anchor.get("href"), context)

    decoded = response.text.replace("\\/", "/").replace("\\u002F", "/")
    for match in re.finditer(
        r'https?://(?:www\.)?sabina\.com/(?:es|it|fr|en|de|nl|pt)/[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(match.group(0), match.group(0))

    for match in re.finditer(
        r'/(?:es|it|fr|en|de|nl|pt)/[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(match.group(0), match.group(0))

    return [url for url, _ in sorted(
        ranked.items(), key=lambda item: (-item[1], item[0])
    )]


def _sitemap_product_urls(session, query):
    """Bounded generic sitemap fallback, used only when native search fails."""
    try:
        response = session.get(
            BASE_URL + "/sitemap.xml",
            headers=HEADERS,
            timeout=DISCOVERY_TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return []

    if response.status_code >= 400:
        return []

    soup = BeautifulSoup(response.text, "xml")
    locs = [clean(loc.get_text()) for loc in soup.find_all("loc")]
    product_sitemaps = [
        url for url in locs
        if "sitemap" in url.lower() and "product" in url.lower()
    ]

    # Some stores expose product URLs directly in sitemap.xml.
    direct = [
        normalise_url(url)
        for url in locs
        if is_product_url(normalise_url(url))
    ]
    direct = [url for url in direct if query_matches(url, query)]
    if direct:
        return list(dict.fromkeys(direct))[:MAX_SITEMAP_CANDIDATES]

    if not product_sitemaps:
        return []

    def fetch_one(url):
        local_session = requests.Session()
        try:
            r = local_session.get(
                url,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
                allow_redirects=True,
            )
            if r.status_code >= 400:
                return []
            xml = BeautifulSoup(r.text, "xml")
            result = []
            for loc in xml.find_all("loc"):
                candidate = normalise_url(loc.get_text())
                if candidate and is_product_url(candidate) and query_matches(candidate, query):
                    result.append(candidate)
            return result
        except requests.RequestException:
            return []
        finally:
            local_session.close()

    found = []
    with ThreadPoolExecutor(max_workers=min(4, len(product_sitemaps))) as pool:
        futures = [pool.submit(fetch_one, url) for url in product_sitemaps[:4]]
        for future in as_completed(futures):
            found.extend(future.result())
            if len(set(found)) >= MAX_SITEMAP_CANDIDATES:
                break

    return list(dict.fromkeys(found))[:MAX_SITEMAP_CANDIDATES]


def _browser_search_product_urls(query):
    """Bounded browser fallback for Sabina's generic native search."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    from urllib.parse import urlencode

    search_url = BASE_URL + "/es/buscar?" + urlencode({"search_query": query})

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    user_agent=HEADERS["User-Agent"],
                    locale="es-ES",
                    extra_http_headers={
                        "Accept-Language": HEADERS["Accept-Language"],
                    },
                )
                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=BROWSER_DISCOVERY_TIMEOUT_MS,
                )
                if BROWSER_DISCOVERY_WAIT_MS > 0:
                    page.wait_for_timeout(BROWSER_DISCOVERY_WAIT_MS)

                html = page.content()
                if not html:
                    return []

                class _BrowserResponse:
                    def __init__(self, text, url):
                        self.text = text
                        self.url = url

                response = _BrowserResponse(html, page.url)
                return _extract_search_candidates(response, query)[:MAX_CANDIDATES]
            finally:
                browser.close()
    except Exception:
        return []


def _sellboost_search_candidates(session, query):
    """Query Sabina's authoritative Italian Sellboost search service.

    Returns a list for a successful search (including [] for zero hits).
    Returns None only for a technical failure so legacy fallback remains
    distinguishable from a valid zero-result search.
    """
    session_id = str(uuid.uuid4())
    payload = {
        "sessionId": session_id,
        "searchTerm": str(query or "").strip(),
        "facets": [],
        "priceFacet": None,
        "country": SELLBOOST_COUNTRY,
        "countryId": SELLBOOST_COUNTRY_ID,
        "currency": SELLBOOST_CURRENCY,
        "excludedBrands": [],
        "excludedProducts": [],
        "group": "1",
        "lastRegisterId": [],
        "registersPerPage": SELLBOOST_REGISTERS_PER_PAGE,
        "searchLanguage": SELLBOOST_LANGUAGE,
        "sorting": {"field": "relevance", "type": "desc"},
        "shopId": SELLBOOST_SHOP_ID,
        "subShopId": SELLBOOST_SUB_SHOP_ID,
    }

    headers = {
        "User-Agent": HEADERS["User-Agent"],
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        "Referer": BASE_URL + "/it/",
    }

    found = []
    seen = set()

    for _ in range(SELLBOOST_MAX_PAGES):
        try:
            response = session.post(
                SELLBOOST_SEARCH_URL,
                json=payload,
                headers=headers,
                timeout=DISCOVERY_TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            return None

        try:
            if response.status_code >= 400:
                return None
            data = response.json()
        except (ValueError, json.JSONDecodeError):
            return None

        if not isinstance(data, dict) or data.get("status") != "success":
            return None

        result_data = data.get("data")
        if not isinstance(result_data, dict):
            return None

        rows = result_data.get("searchResponses")
        if rows is None or not isinstance(rows, list):
            return None

        for row in rows:
            if not isinstance(row, dict):
                continue
            candidate = normalise_url(row.get("url"))
            if not candidate or not is_product_url(candidate):
                continue
            if candidate in seen:
                continue
            seen.add(candidate)
            found.append(candidate)
            if len(found) >= MAX_CANDIDATES:
                return found[:MAX_CANDIDATES]

        last_register_id = result_data.get("lastRegisterId")
        if not last_register_id:
            break
        payload["lastRegisterId"] = (
            last_register_id
            if isinstance(last_register_id, list)
            else [last_register_id]
        )

    return found[:MAX_CANDIDATES]


def _sellboost_search_product_urls(session, query):
    """Compatibility wrapper preserving technical-failure semantics."""
    return _sellboost_search_candidates(session, query)


def _legacy_search_product_urls(session, query):
    """Legacy generic discovery used only if Sellboost technically fails."""
    native_candidates = []
    seen = set()

    for endpoint, param_template in SEARCH_ENDPOINTS:
        params = {
            key: (query if value is True else value)
            for key, value in param_template.items()
        }
        try:
            response = session.get(
                endpoint,
                params=params,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if response.status_code >= 400:
            continue

        candidates = _extract_search_candidates(response, query)
        for candidate in candidates:
            if candidate not in seen:
                seen.add(candidate)
                native_candidates.append(candidate)

        strong = [candidate for candidate in native_candidates if query_matches(candidate, query)]
        if strong:
            ranked = sorted(
                native_candidates,
                key=lambda candidate: (-_candidate_score(candidate, "", query), candidate),
            )
            return ranked[:MAX_CANDIDATES]

    browser_candidates = _browser_search_product_urls(query)
    merged = list(native_candidates)
    for candidate in browser_candidates:
        if candidate not in seen:
            seen.add(candidate)
            merged.append(candidate)

    strong = [candidate for candidate in merged if query_matches(candidate, query)]
    if strong:
        ranked = sorted(
            merged,
            key=lambda candidate: (-_candidate_score(candidate, "", query), candidate),
        )
        return ranked[:MAX_CANDIDATES]

    return _sitemap_product_urls(session, query)[:MAX_CANDIDATES]


def _discover_product_candidates(session, query):
    """Prefer Sabina's Spanish storefront; use Sellboost only as fallback.

    Sellboost is configured for the Italian market (country=IT). Its results
    must not take priority over Sabina's Spanish native catalogue, because the
    resulting product page and its customer-facing price can belong to a
    different national storefront. The product-page parser remains the source
    of the price; this function only chooses where product URLs are discovered.
    """
    spanish_candidates = _legacy_search_product_urls(session, query)
    if spanish_candidates:
        return [(url, False) for url in spanish_candidates[:MAX_CANDIDATES]]

    # Fallback only: the Sellboost integration is explicitly Italian.
    sellboost_candidates = _sellboost_search_candidates(session, query)
    if sellboost_candidates:
        return [(url, True) for url in sellboost_candidates[:MAX_CANDIDATES]]

    return []


def discover_product_urls(session, query):
    """Compatibility API returning URLs only."""
    return [url for url, _authoritative in _discover_product_candidates(session, query)]


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


def extract_product_page(session, url, query, authoritative_search=False, html=None):
    # The catalog engine supplies HTML for an already-identified product URL.
    # Reuse that response and do not treat URL path tokens (locale, category,
    # numeric product ID) as required product-name tokens.
    if html is None:
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
        page_html = response.text
        status_code = response.status_code
    else:
        final_url = normalise_url(url)
        page_html = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else str(html)
        status_code = 200

    if not final_url or not is_product_url(final_url):
        return None

    soup = BeautifulSoup(
        page_html,
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

    # Search discovery must validate relevance; exact-URL catalog refresh must
    # parse the identified product even when the URL contains locale/category/ID
    # tokens that are absent from its commercial title.
    if html is None and not authoritative_search and not query_matches(
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

    # Collect size-specific offers from structured data and variant controls.
    # Do not infer a price from unrelated product cards or from the selected
    # page price: a variant is emitted only when size and its own price are
    # both present in the same offer/control or embedded variant object.
    variants = []
    seen_variant_keys = set()

    def add_variant(raw_size, raw_price, currency="EUR", availability=None, sku=None, variant_url=None, gtin=None, mpn=None, variant_id=None):
        variant_size = extract_size_ml(raw_size)
        variant_price = money_to_float(raw_price)
        if variant_size is None or (
            variant_price is None and availability != "out_of_stock"
        ) or (variant_price is not None and variant_price <= 0):
            return
        # A variant is not identified by size and price alone. Retailers can
        # legitimately expose separate combinations with the same price/SKU,
        # while one product-level SKU may be inherited by every size. Preserve
        # distinct retailer combination IDs and direct variant URLs.
        key = (
            round(float(variant_size), 2),
            round(float(variant_price), 2) if variant_price is not None else None,
            clean(sku),
            str(variant_id or "").strip(),
            clean(gtin),
            clean(mpn),
            clean(variant_url),
        )
        if key in seen_variant_keys:
            return
        seen_variant_keys.add(key)
        # Keep the retailer's real combination ID in the URL fragment. A
        # size-only fragment is not sufficient: Sabina's selector is keyed by
        # id_product_attribute (e.g. #/25-tama_o-50_ml).
        target_url = clean(variant_url) or final_url
        target_parts = urlparse(target_url)
        is_sabina_url = (target_parts.hostname or "").lower().rstrip(".") in {
            "sabina.com", "www.sabina.com"
        }
        if is_sabina_url and variant_size is not None:
            fragment = target_parts.fragment
            valid_fragment = re.search(r"(?:^|/)\d+-tama_o-\d+(?:_\d+)?_ml$", fragment, re.I)
            if not valid_fragment:
                if str(variant_id or "").strip().isdigit():
                    size_label = f"{float(variant_size):g}".replace(".", "_")
                    target_url = target_url.split("#", 1)[0] + f"#/{int(variant_id)}-tama_o-{size_label}_ml"
                else:
                    # Never emit a guessed size-only fragment as a variant URL.
                    target_url = target_url.split("#", 1)[0]
        variants.append({
            "size_ml": float(variant_size),
            "price_num": float(variant_price) if variant_price is not None else None,
            "currency": clean(currency) or "EUR",
            "availability": availability or "unknown", "sku": clean(sku) or None,
            "gtin": clean(gtin) or None, "mpn": clean(mpn) or None,
            "url": target_url,
        })

    for variant_offer in _offer_list(product or {}):
        add_variant(
            " ".join(str(variant_offer.get(k) or "") for k in ("name", "description", "sku", "url")),
            variant_offer.get("price"), variant_offer.get("priceCurrency"),
            availability_from_product_page(soup, variant_offer)[0],
            variant_offer.get("sku"), variant_offer.get("url"),
            next((variant_offer.get(k) for k in ("gtin13", "gtin12", "gtin14", "gtin") if variant_offer.get(k)), None),
            variant_offer.get("mpn"),
            next((variant_offer.get(k) for k in (
                "id_product_attribute", "id_product_attribute_value",
                "combination_id", "variant_id", "idProductAttribute",
            ) if str(variant_offer.get(k) or "").strip().isdigit()), None),
        )

    # Sabina's selector often keeps the full variant matrix in embedded JSON
    # rather than in Product.offers. Walk JSON script payloads and accept only
    # objects that independently contain a size-like field and a price field.
    size_keys = ("size", "size_ml", "volume", "attribute", "label", "name", "title", "value", "public_name")
    price_keys = ("price", "price_amount", "priceAmount", "amount", "final_price", "finalPrice", "current_price", "currentPrice")
    # Keep product-level IDs out of SKU inheritance: id_product/id often
    # identify the parent page, not a purchasable size combination.
    sku_keys = ("sku", "reference", "reference_to_display", "product_reference")
    variant_id_keys = (
        "id_product_attribute", "id_product_attribute_value",
        "combination_id", "variant_id", "id_variant",
        "idProductAttribute", "combinationId",
    )
    gtin_keys = ("gtin13", "gtin12", "gtin14", "gtin", "ean", "ean13")
    mpn_keys = ("mpn", "manufacturer_part_number", "manufacturerPartNumber")
    def walk_variant_data(obj, inherited_sku=None, inherited_variant=None):
        """Extract nested Product -> Offer pairs without mixing format prices.

        Schema.org commonly stores a variant's size and URL on its Product
        object, while its own price and availability live one level deeper in
        offers. Carry that variant context into descendants, but never carry a
        parent's price into a child or a selected format into sibling variants.
        """
        if isinstance(obj, dict):
            size_values = [obj.get(k) for k in size_keys if obj.get(k) not in (None, "")]
            local_size = next((v for v in size_values if extract_size_ml(v) is not None), None)
            local_sku = next((obj.get(k) for k in sku_keys if obj.get(k) not in (None, "")), None)
            effective_sku = local_sku if local_sku is not None else inherited_sku
            local_variant_id = next(
                (obj.get(k) for k in variant_id_keys
                 if str(obj.get(k) or "").strip().isdigit()),
                None,
            )
            local_gtin = next((obj.get(k) for k in gtin_keys if obj.get(k) not in (None, "")), None)
            local_mpn = next((obj.get(k) for k in mpn_keys if obj.get(k) not in (None, "")), None)

            # A Product node can carry format/URL while its nested Offer owns
            # the price. Only establish inherited context from an object that
            # actually identifies a size, so parent product prices are not
            # propagated to every variant.
            current_variant = inherited_variant
            if local_size is not None:
                current_variant = {
                    "size": local_size,
                    "url": obj.get("url") or (inherited_variant or {}).get("url"),
                    "variant_id": local_variant_id,
                    "sku": effective_sku,
                    "gtin": local_gtin,
                    "mpn": local_mpn,
                }

            price_values = [obj.get(k) for k in price_keys if obj.get(k) not in (None, "")]
            price = next((v for v in price_values if money_to_float(v) is not None), None)
            effective_size = local_size if local_size is not None else (current_variant or {}).get("size")
            if effective_size is not None:
                currency = obj.get("priceCurrency") or obj.get("currency") or "EUR"
                raw_availability = clean(
                    obj.get("availability") or obj.get("stock_status")
                    or obj.get("availability_status")
                ).lower()
                if any(x in raw_availability for x in ("outofstock", "out_of_stock", "unavailable", "soldout")):
                    availability = "out_of_stock"
                elif any(x in raw_availability for x in ("instock", "in_stock", "available")):
                    availability = "in_stock"
                else:
                    availability = "unknown"
                # Keep a sold-out variant even when its retailer page omits
                # price; it must clear an older purchasable offer. Never carry
                # a parent or sibling variant's price into this record.
                if price is not None or availability == "out_of_stock":
                    variant_context = current_variant or {}
                    add_variant(
                        effective_size, price, currency, availability,
                        effective_sku or variant_context.get("sku"),
                        obj.get("url") or variant_context.get("url"),
                        local_gtin or variant_context.get("gtin"),
                        local_mpn or variant_context.get("mpn"),
                        local_variant_id or variant_context.get("variant_id"),
                    )

            for value in obj.values():
                walk_variant_data(value, effective_sku, current_variant)
        elif isinstance(obj, list):
            for value in obj:
                walk_variant_data(value, inherited_sku, inherited_variant)

    # Read both explicit JSON script blocks and valid JSON objects embedded in
    # JavaScript configuration scripts. Sabina may expose combinations through
    # a JS bootstrap object instead of application/json. Only parse actual JSON
    # fragments; never evaluate JavaScript.
    json_decoder = json.JSONDecoder()
    for script in soup.select("script"):
        raw_json = script.string or script.get_text()
        if not raw_json or len(raw_json) > 2_000_000:
            continue
        raw_json = raw_json.strip()
        parsed_any = False
        try:
            walk_variant_data(json.loads(raw_json))
            parsed_any = True
        except (ValueError, TypeError, RecursionError):
            pass
        if parsed_any:
            continue
        # Limit fragment scanning to scripts that plausibly carry product or
        # variant data, avoiding unrelated analytics/config payloads.
        if not re.search(r"variant|combination|attribute|product|price|volume|size", raw_json, re.I):
            continue
        for match in re.finditer(r"[\[{]", raw_json):
            try:
                fragment, _end = json_decoder.raw_decode(raw_json[match.start():])
            except (ValueError, TypeError, RecursionError):
                continue
            if isinstance(fragment, (dict, list)):
                try:
                    walk_variant_data(fragment)
                except (TypeError, RecursionError):
                    continue

    # Variant controls can carry size and price together in data attributes.
    # A label-only control is deliberately not assigned the selected page price.
    for node in soup.select('option, [data-size], [data-product-size], [data-volume], [data-variant], [data-product-attribute]'):
        attrs = node.attrs if hasattr(node, "attrs") else {}
        label = clean(node.get_text(" ", strip=True))
        raw_size = " ".join([label] + [str(attrs.get(k) or "") for k in ("value", "data-size", "data-product-size", "data-volume", "aria-label", "title")])
        raw_price = next((attrs.get(k) for k in ("data-price", "data-product-price", "data-final-price", "data-price-amount") if attrs.get(k) not in (None, "")), None)
        if raw_price is None:
            continue
        add_variant(raw_size, raw_price, attrs.get("data-currency") or "EUR", None,
                    attrs.get("data-sku"), attrs.get("data-url"), variant_id=attrs.get("data-id-product-attribute"))

    price = (
        money_to_float(offer.get("price"))
        if isinstance(offer, dict)
        else None
    )
    price_source = "sabina_jsonld"

    # This is the base product-page price only. It must never be copied into
    # the variants array: each variant is admitted only from its own size/price
    # pair above. Catalog search must prefer the variant table when available.
    # The fallback deliberately ignores struck-through/reference prices.
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
            final_url,
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

    # The full page body includes recommendations and related products.
    # Infer gender from the current product title to avoid cross-product bleed.
    gender, gender_source = extract_gender(title)

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

        "variants": variants,

        "raw_data": {
            "product_url": final_url,
            "status_code": status_code,
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

def _fallback_extract_product_page(session, url, query, authoritative_search=False):
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
    if not title:
        return None
    if not authoritative_search and not query_matches(title, query):
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


def _fetch_candidate(url, query, authoritative_search=False):
    # One Session per worker avoids sharing requests.Session across threads.
    # IMPORTANT: do not issue a second HTTP request merely because the rich
    # parser returned None. That doubled the worst-case product-page budget
    # and could push this scraper past Main's 45s store timeout.
    local_session = requests.Session()
    try:
        try:
            return extract_product_page(local_session, url, query, authoritative_search=authoritative_search)
        except Exception:
            # The fallback is allowed only when the parser itself raises; it
            # must never be used as a second request after a normal rejection.
            try:
                return _fallback_extract_product_page(local_session, url, query, authoritative_search=authoritative_search)
            except Exception:
                return None
    finally:
        local_session.close()


def search(query):
    query = clean(query)

    if not query:
        return []

    session = requests.Session()

    try:
        candidates = _discover_product_candidates(session, query)
        if not candidates:
            return []

        results = []
        seen = set()

        # Product pages are independent. Fetch them concurrently so one slow
        # product cannot consume the entire store timeout budget.
        with ThreadPoolExecutor(
            max_workers=min(PRODUCT_WORKERS, len(candidates))
        ) as pool:
            futures = {
                pool.submit(
                    _fetch_candidate,
                    url,
                    query,
                    authoritative_search,
                ): url
                for url, authoritative_search in candidates[:MAX_CANDIDATES]
            }

            for future in as_completed(futures):
                product = future.result()
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
