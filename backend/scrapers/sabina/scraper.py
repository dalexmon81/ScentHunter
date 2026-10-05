import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
import uuid
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"

# Sabina's Italian JavaScript search is backed by Sellboost. This is the
# retailer-authoritative discovery surface used before product-page hydration.
SELLBOOST_SEARCH_URL = "https://api.sellboost.com/finder/search"
SELLBOOST_SHOP_ID = "fd08e30c-8347-4a9f-ae40-94463e3d1e59"
SELLBOOST_SUB_SHOP_ID = "shop|1"
SELLBOOST_COUNTRY = "IT"
SELLBOOST_COUNTRY_ID = 10
SELLBOOST_LANGUAGE = "it"
SELLBOOST_CURRENCY = "EUR"
SELLBOOST_REGISTERS_PER_PAGE = 50
SELLBOOST_MAX_PAGES = 10
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
                return _extract_search_candidates(
                    response, query
                )[:MAX_CANDIDATES]
            finally:
                browser.close()
    except Exception:
        return []


def _sellboost_search_candidates(session, query):
    """Return Sabina product URLs from the retailer-authoritative search API.

    ``None`` means the Sellboost request failed technically and the legacy
    discovery path may be used as a bounded fallback. ``[]`` means the
    authoritative search completed successfully with zero products and must
    be respected as such.
    """
    search_term = clean(query)
    if not search_term:
        return []

    candidates = []
    seen = set()
    last_register_id = []

    for _page in range(SELLBOOST_MAX_PAGES):
        payload = {
            "sessionId": str(uuid.uuid4()),
            "searchTerm": search_term,
            "facets": [],
            "priceFacet": None,
            "country": SELLBOOST_COUNTRY,
            "countryId": SELLBOOST_COUNTRY_ID,
            "currency": SELLBOOST_CURRENCY,
            # These exclusions are intentionally empty. The exclusions seen in
            # Sabina's browser payload are UI/session-specific and must not be
            # hard-coded into ScentHunter's generic retailer discovery.
            "excludedBrands": [],
            "excludedProducts": [],
            "group": "1",
            "lastRegisterId": last_register_id,
            "registersPerPage": SELLBOOST_REGISTERS_PER_PAGE,
            "searchLanguage": SELLBOOST_LANGUAGE,
            "sorting": {
                "field": "relevance",
                "type": "desc",
            },
            "shopId": SELLBOOST_SHOP_ID,
            "subShopId": SELLBOOST_SUB_SHOP_ID,
        }

        try:
            response = session.post(
                SELLBOOST_SEARCH_URL,
                json=payload,
                headers=HEADERS,
                timeout=DISCOVERY_TIMEOUT,
            )
        except requests.RequestException:
            return None

        try:
            if response.status_code >= 400:
                return None

            body = response.json()
        except (ValueError, requests.RequestException):
            return None
        finally:
            response.close()

        if not isinstance(body, dict) or body.get("status") != "success":
            return None

        data = body.get("data")
        if not isinstance(data, dict):
            return None

        rows = data.get("searchResponses")
        if not isinstance(rows, list):
            rows = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_url = row.get("url")
            absolute = normalise_url(raw_url, BASE_URL)
            if not absolute or not is_product_url(absolute):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            candidates.append(absolute)
            if len(candidates) >= MAX_CANDIDATES:
                return candidates

        next_register_id = data.get("lastRegisterId")
        if not next_register_id:
            break

        # Sellboost returns the pagination cursor as a list in the captured
        # Sabina request/response contract. Preserve it exactly for the next
        # page, while avoiding an accidental infinite loop.
        if next_register_id == last_register_id:
            break
        last_register_id = (
            next_register_id
            if isinstance(next_register_id, list)
            else [next_register_id]
        )

    return candidates


def _sellboost_search_product_urls(session, query):
    """Compatibility wrapper returning only authoritative product URLs."""
    return _sellboost_search_candidates(session, query) or []


def _legacy_search_product_urls(session, query):
    """Legacy heuristic discovery used only when Sellboost fails technically."""
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

        strong = [
            candidate
            for candidate in native_candidates
            if query_matches(candidate, query)
        ]
        if strong:
            ranked = sorted(
                native_candidates,
                key=lambda url: (
                    0 if url in strong else 1,
                    -_candidate_score(url, "", query),
                    url,
                ),
            )
            return ranked[:MAX_CANDIDATES]

    browser_candidates = _browser_search_product_urls(query)
    for candidate in browser_candidates:
        if candidate not in seen:
            seen.add(candidate)
            native_candidates.append(candidate)

    strong = [
        candidate
        for candidate in native_candidates
        if query_matches(candidate, query)
    ]
    if strong:
        ranked = sorted(
            native_candidates,
            key=lambda url: (
                0 if url in strong else 1,
                -_candidate_score(url, "", query),
                url,
            ),
        )
        return ranked[:MAX_CANDIDATES]

    return _sitemap_product_urls(session, query)[:MAX_SITEMAP_CANDIDATES]


def _discover_product_candidates(session, query):
    """Return ``(url, authoritative_search)`` discovery candidates.

    Sabina's Sellboost search is authoritative. We use weaker HTML/browser/
    sitemap discovery only when the authoritative request itself fails
    technically. A valid zero-result from Sellboost is not replaced by
    heuristic guesses.
    """
    sellboost_candidates = _sellboost_search_candidates(session, query)
    if sellboost_candidates is not None:
        return [(url, True) for url in sellboost_candidates]

    legacy = _legacy_search_product_urls(session, query)
    return [(url, False) for url in legacy]


def discover_product_urls(session, query):
    """Compatibility API returning only discovered product URLs."""
    return [
        url
        for url, _authoritative in _discover_product_candidates(session, query)
    ]


def _fetch_candidate(url, query, authoritative_search=False):
    # One Session per worker avoids sharing requests.Session across threads.
    # IMPORTANT: do not issue a second HTTP request merely because the rich
    # parser returned None. That doubled the worst-case product-page budget
    # and could push this scraper past Main's 45s store timeout.
    local_session = requests.Session()
    try:
        try:
            return extract_product_page(local_session, url, query, authoritative_search)
        except Exception:
            # The fallback is allowed only when the parser itself raises; it
            # must never be used as a second request after a normal rejection.
            try:
                return _fallback_extract_product_page(local_session, url, query, authoritative_search)
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
        candidate_candidates = _discover_product_candidates(session, query)
        if not candidate_candidates:
            return []

        results = []
        seen = set()

        # Product pages are independent. Fetch them concurrently so one slow
        # product cannot consume the entire store timeout budget.
        with ThreadPoolExecutor(
            max_workers=min(PRODUCT_WORKERS, len(candidate_candidates))
        ) as pool:
            futures = {
                pool.submit(
                    _fetch_candidate,
                    url,
                    query,
                    authoritative_search,
                ): (url, authoritative_search)
                for url, authoritative_search in candidate_candidates[:MAX_CANDIDATES]
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
