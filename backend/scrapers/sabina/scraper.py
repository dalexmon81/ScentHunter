import json
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
BASE = BASE_URL
SEARCH_URL = BASE_URL + "/es/buscar"
TIMEOUT = 5
MAX_CANDIDATES = 8
PRODUCT_WORKERS = 4

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


# Compatibilita con sitecustomize.py: mantiene il nome atteso dal wrapper.
_clean = clean


_clean = clean


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


def extract_concentration_from_product_page(
    soup,
    title="",
    product=None,
):
    """
    Read concentration only from product-specific data.

    The full Sabina page can contain recommendations/related products with
    other concentrations. Those unrelated blocks must never determine the
    selected product's concentration.
    """
    texts = []

    if title:
        texts.append(title)

    if isinstance(product, dict):
        for key in ("name", "description"):
            value = product.get(key)
            if value:
                texts.append(str(value))

    for selector in (
        '[itemprop="description"]',
        '[itemprop="name"]',
        '[class*="product-information"]',
        '[class*="product-detail"]',
        '[class*="product-description"]',
        '[class*="product-attribute"]',
        '[class*="product-variant"]',
        '[class*="product-combination"]',
    ):
        for node in soup.select(selector):
            text = node.get_text(" ", strip=True)
            if text:
                texts.append(text)

    # Prefer the product's explicit Eau de Parfum/Toilette wording before
    # falling back to other concentration labels.
    combined = norm(" ".join(texts))
    priority_rules = (
        ("Eau de Parfum", (r"\beau\s+de\s+parfum\b", r"\bedp\b")),
        ("Eau de Toilette", (r"\beau\s+de\s+toilette\b", r"\bedt\b")),
        ("Eau de Cologne", (r"\beau\s+de\s+cologne\b", r"\bedc\b")),
        ("Extrait de Parfum", (r"\bextrait\s+(?:de\s+)?parfum\b",)),
        ("Parfum", (r"\bparfum\b",)),
    )

    for label, patterns in priority_rules:
        for pattern in patterns:
            if re.search(pattern, combined, re.I):
                return label, "product_page"

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
    Generic Sabina product-price extraction.

    Priority:
    1. Explicit live product price labelled "Precio:" (or equivalent).
    2. Product price metadata.
    3. Current-price DOM elements.
    4. Product-area currency fallback.

    The explicit live-price label is evaluated before generic price classes
    because Sabina can expose stale/hidden variant prices in those elements.
    """
    # First: explicit live price in the product page text.
    # The first occurrence belongs to the product block, before related items.
    page_text = clean(soup.get_text(" ", strip=True))
    live_price = re.search(
        r"\b(?:precio|price|prix|preis)\s*[:\-]\s*"
        r"(?:(?:€|eur|\$|usd|£|gbp)\s*)?"
        r"([0-9][0-9\s.,]*)\s*"
        r"(?:€|eur|\$|usd|£|gbp)?",
        page_text,
        re.I,
    )
    if live_price:
        value = money_to_float(live_price.group(1))
        if value is not None:
            return value, "sabina_html_price"

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
    Read the selected product size from product-specific content.

    Sabina exposes the selected variant as plain text such as
    "Tamaño: 150 ML". This labelled product value is preferred before
    broader DOM selectors so related-product cards cannot supply the size.
    """
    page_text = clean(soup.get_text(" ", strip=True))

    # The first labelled product size occurs in the product block, before
    # related-product cards. No product-specific names or IDs are used.
    labelled_size = re.search(
        r"\b(?:tama(?:ñ|n)o|size|taille|formato|volume)\s*"
        r"[:\-]?\s*(\d+(?:[.,]\d+)?)\s*"
        r"(?:ml|millilitros?|milliliters?)\b",
        page_text,
        re.I,
    )

    if labelled_size:
        value = extract_size_ml(labelled_size.group(0))
        if value is not None:
            return value, "product_page"

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

    for selector in selectors:
        for node in soup.select(selector):
            raw = clean(
                node.get_text(" ", strip=True)
            )
            if not raw:
                continue

            value = extract_size_ml(raw)
            if value is not None:
                return value, "product_page"

    value = extract_size_ml(title)
    if value is not None:
        return value, "product_text"

    return None, None

def availability_from_product_page(soup, jsonld_offer=None):
    """
    Determine availability from product-page purchase evidence.

    Priority:
      1. Active product-specific purchase control -> in_stock.
      2. Disabled product-specific purchase control -> out_of_stock.
      3. Explicit positive stock data -> in_stock.
      4. Explicit negative stock data -> out_of_stock only when no
         purchase control exists.
      5. Otherwise -> unknown.

    Generic notification/date text is never proof of out_of_stock.
    """
    explicit_in_stock = False
    explicit_out_of_stock = False
    explicit_preorder = False

    if isinstance(jsonld_offer, dict):
        raw = clean(jsonld_offer.get("availability")).lower()

        if "instock" in raw or "in stock" in raw:
            explicit_in_stock = True
        elif "preorder" in raw:
            explicit_preorder = True
        elif any(
            token in raw
            for token in (
                "outofstock",
                "out of stock",
                "soldout",
                "sold out",
            )
        ):
            explicit_out_of_stock = True

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
                    "content",
                    "href",
                    "data-availability",
                    "data-stock-status",
                    "data-product-availability",
                )
            )
            raw = clean(
                f"{raw} {node.get_text(' ', strip=True)}"
            ).lower()

            if "instock" in raw or "in stock" in raw:
                explicit_in_stock = True

            if any(
                token in raw
                for token in (
                    "outofstock",
                    "out of stock",
                    "soldout",
                    "sold out",
                    "unavailable",
                )
            ):
                explicit_out_of_stock = True

    purchase_roots = soup.select(
        "main, #main, .product-container, .product-information, "
        ".product-detail, .product-page, .product-actions, "
        ".product-add-to-cart, .product-combination, form"
    ) or [soup]

    purchase_words = (
        "añadir al carrito",
        "agregar al carrito",
        "comprar",
        "add to cart",
        "add-to-cart",
        "buy now",
        "ajouter au panier",
        "acheter",
        "in den warenkorb",
        "jetzt kaufen",
        "acquista",
        "aggiungi al carrello",
    )

    purchase_markers = (
        "add-to-cart",
        "add_to_cart",
        "addtocart",
        "add-cart",
        "product-add-to-cart",
        "product_add_to_cart",
        "buy-now",
        "buy_now",
        "purchase",
        "cart-add",
        "cart_add",
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

            raw = norm(
                " ".join(
                    [
                        node.get_text(" ", strip=True),
                        node.get("value", ""),
                        node.get("aria-label", ""),
                        node.get("title", ""),
                        " ".join(node.get("class", [])),
                        node.get("data-button-action", ""),
                        node.get("data-action", ""),
                        node.get("name", ""),
                        node.get("id", ""),
                    ]
                )
            )

            if not any(word in raw for word in purchase_words) and not any(
                marker in raw for marker in purchase_markers
            ):
                continue

            disabled = (
                node.has_attr("disabled")
                or str(node.get("aria-disabled", "")).lower() == "true"
                or "disabled" in node.get("class", [])
            )

            if disabled:
                has_disabled_purchase = True
            else:
                has_purchase = True

    # Fallback for ecommerce forms whose purchase button has no recognizable
    # text/class: a quantity field plus an enabled submit control in the
    # product area is a real purchase path.
    for form in soup.select(
        "main form, #main form, .product-container form, "
        ".product-information form, .product-detail form, "
        ".product-page form, .product-actions form"
    ):
        quantity = form.select_one(
            'input[name*="qty" i], '
            'input[name*="quantity" i], '
            'input[name*="cantidad" i], '
            'input[id*="qty" i], '
            'input[id*="quantity" i], '
            'input[id*="cantidad" i]'
        )

        if not quantity:
            continue

        quantity_disabled = (
            quantity.has_attr("disabled")
            or str(quantity.get("aria-disabled", "")).lower() == "true"
        )

        enabled_control = False
        disabled_control = False

        for control in form.select(
            'button, input[type="submit"], input[type="button"]'
        ):
            disabled = (
                control.has_attr("disabled")
                or str(control.get("aria-disabled", "")).lower() == "true"
                or "disabled" in control.get("class", [])
            )

            if disabled:
                disabled_control = True
            else:
                enabled_control = True

        if enabled_control and not quantity_disabled:
            has_purchase = True
        elif disabled_control or quantity_disabled:
            has_disabled_purchase = True

    # Active purchase evidence ALWAYS wins over contradictory/stale metadata.
    if has_purchase:
        return "in_stock", "sabina_purchase_control"

    if explicit_in_stock:
        return "in_stock", "sabina_html_availability"

    if has_disabled_purchase:
        return "out_of_stock", "sabina_purchase_control"

    if explicit_out_of_stock:
        return "out_of_stock", "sabina_html_availability"

    if explicit_preorder:
        return "preorder", "sabina_jsonld"

    return "unknown", "sabina_html_availability"
def discover_product_urls(session, query):
    """Discover real Sabina product URLs without browser automation.

    Try current/legacy first-party search routes, then fall back to the
    public sitemap. Discovery is entirely query-driven: no product URL,
    SKU or product name is hard-coded.
    """
    queries = [clean(query)]
    q_without_size = clean(re.sub(
        r"(?<!\d)\d{2,4}\s*ml\b", " ", query, flags=re.I
    ))
    if q_without_size and norm(q_without_size) != norm(query):
        queries.append(q_without_size)

    urls = []
    seen = set()

    def add(raw, base_url=BASE_URL):
        absolute = normalise_url(raw, base_url)
        if not absolute or not is_product_url(absolute):
            return
        if absolute not in seen:
            seen.add(absolute)
            urls.append(absolute)

    for search_query in queries:
        q = search_query
        encoded = __import__("urllib.parse", fromlist=["quote_plus"]).quote_plus(q)
        routes = (
            f"{BASE_URL}/en/search?controller=search&s={encoded}",
            f"{BASE_URL}/en/search?s={encoded}",
            f"{BASE_URL}/es/buscar?search_query={encoded}",
            f"{BASE_URL}/es/buscar?s={encoded}",
            f"{BASE_URL}/it/ricerca?controller=search&s={encoded}",
            f"{BASE_URL}/it/ricerca?search_query={encoded}",
            f"{BASE_URL}/it/ricerca_old?s={encoded}",
        )

        for search_url in routes:
            try:
                response = session.get(
                    search_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
            except requests.RequestException:
                continue

            if response.status_code >= 400:
                response.close()
                continue

            body = response.text or ""
            soup = BeautifulSoup(body, "html.parser")

            for anchor in soup.find_all("a", href=True):
                add(anchor.get("href"), response.url)

            decoded = body.replace("\\/", "/").replace("\\u002F", "/")
            for match in re.finditer(
                r'https?://(?:www\.)?sabina\.com/(?:es|it|fr|en|de|nl|pt)/[^"\'<>\s\\]+',
                decoded,
                re.I,
            ):
                add(match.group(0), response.url)
            for match in re.finditer(
                r'/(?:es|it|fr|en|de|nl|pt)/[^"\'<>\s\\]+',
                decoded,
                re.I,
            ):
                add(match.group(0), response.url)

            response.close()
            if len(urls) >= MAX_CANDIDATES:
                return urls[:MAX_CANDIDATES]

    # Category fallback: Sabina's product pages are exposed in category
    # listings even when the internal search endpoint returns an empty shell.
    category_urls = (
        f"{BASE_URL}/it/profumi-da-uomo/",
        f"{BASE_URL}/it/profumi-di-donna/",
        f"{BASE_URL}/en/men-perfumes/",
        f"{BASE_URL}/en/women-perfumes/",
    )
    query_tokens = [t for t in norm(query).split() if len(t) > 1 and t != "ml"]
    for category_url in category_urls:
        try:
            response = session.get(category_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except requests.RequestException:
            continue
        if response.status_code >= 400 or not response.text:
            response.close()
            continue
        body = response.text or ""
        page_url = response.url
        soup = BeautifulSoup(body, "html.parser")
        anchors = soup.find_all("a", href=True)
        for anchor in anchors:
            href = anchor.get("href")
            text = clean(anchor.get_text(" ", strip=True))
            hay = norm(text + " " + (href or ""))
            if query_tokens and all(t in hay for t in query_tokens):
                add(href, page_url)
            elif href and query_tokens and all(t in norm(href) for t in query_tokens):
                add(href, page_url)
            if len(urls) >= MAX_CANDIDATES:
                response.close()
                return urls[:MAX_CANDIDATES]
        response.close()

    # Generic public sitemap fallback. This is especially useful when the
    # storefront search endpoint is blocked or returns an empty shell.
    sitemap_urls = [
        f"{BASE_URL}/sitemap.xml",
        f"{BASE_URL}/it/sitemap.xml",
        f"{BASE_URL}/es/sitemap.xml",
    ]
    tokens = [t for t in norm(query).split() if len(t) > 1 and t != "ml"]

    for sitemap_url in sitemap_urls:
        try:
            response = session.get(
                sitemap_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue
        if response.status_code >= 400 or not response.text:
            response.close()
            continue

        body = response.text
        response.close()
        try:
            xml = BeautifulSoup(body, "xml")
            locs = [clean(x.get_text()) for x in xml.find_all("loc")]
        except Exception:
            locs = re.findall(r"<loc>\s*(.*?)\s*</loc>", body, re.I | re.S)

        child_maps = [u for u in locs if u.lower().endswith(".xml") and "sitemap" in u.lower()]
        product_locs = [u for u in locs if is_product_url(u)]

        for child in child_maps[:4]:
            try:
                r = session.get(child, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                if r.status_code < 400 and r.text:
                    try:
                        child_xml = BeautifulSoup(r.text, "xml")
                        product_locs.extend(clean(x.get_text()) for x in child_xml.find_all("loc"))
                    except Exception:
                        pass
                r.close()
            except requests.RequestException:
                continue

        for raw in product_locs:
            candidate = normalise_url(raw)
            if not candidate or not is_product_url(candidate):
                continue
            haystack = norm(re.sub(r"[-_/]+", " ", urlparse(candidate).path))
            if tokens and all(token in haystack for token in tokens):
                add(candidate)
                if len(urls) >= MAX_CANDIDATES:
                    return urls[:MAX_CANDIDATES]

    return urls[:MAX_CANDIDATES]


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

    # Prefer the offer whose URL/name identifies the same product page.
    same_product = []
    for offer in offers:
        offer_url = normalise_url(offer.get("url"))
        offer_name = clean(offer.get("name"))
        if offer_url == final_url:
            same_product.append(offer)
        elif offer_name and query_matches(
            f"{offer_name} {title}", title
        ):
            same_product.append(offer)

    candidates = same_product or offers

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
        elif any(_offer_size(offer, product) is not None for offer in candidates):
            return None

    # Prefer an offer with a real price and otherwise keep the first
    # product-bound offer.
    priced = [
        offer for offer in candidates
        if money_to_float(offer.get("price")) is not None
    ]
    return priced[0] if priced else candidates[0]



def extract_variant_offers_from_page(soup):
    """Return explicit size/price pairs exposed by the current product page."""
    chunks = []
    for node in soup.find_all(["option", "label", "button", "li", "div", "span"], limit=3000):
        text = clean(node.get_text(" ", strip=True))
        if not text:
            continue
        if re.search(r"\b\d+(?:[.,]\d+)?\s*ml\b", text, re.I) and re.search(r"\d+[.,]\d{2}\s*(?:€|EUR)", text, re.I):
            chunks.append(text)
    page_text = clean(soup.get_text(" ", strip=True))
    if page_text:
        chunks.append(page_text)

    variants = []
    seen = set()
    for chunk in chunks:
        for sm in re.finditer(r"\b(\d+(?:[.,]\d+)?)\s*ml\b", chunk, re.I):
            size = extract_size_ml(sm.group(0))
            if size is None:
                continue
            tail = chunk[sm.end():sm.end()+180]
            pm = re.search(r"(\d+[.,]\d{2})\s*(?:€|EUR)", tail, re.I)
            if not pm:
                continue
            price = money_to_float(pm.group(1))
            if price is None:
                continue
            key = (float(size), round(price, 2))
            if key not in seen:
                seen.add(key)
                variants.append((size, price))
    return sorted(variants, key=lambda x: x[0])

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

    product = first_jsonld_product(soup)

    h1 = soup.select_one("h1")
    h1_text = (
        clean(h1.get_text(" ", strip=True))
        if h1
        else ""
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
        extract_concentration_from_product_page(
            soup,
            title,
            product,
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
            "variant_offers": extract_variant_offers_from_page(soup),
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

def _fetch_product(url, query):
    session = requests.Session()
    try:
        return extract_product_page(session, url, query)
    except requests.RequestException:
        return None
    except Exception:
        return None
    finally:
        session.close()



def diagnostic_search(query):
    """Verbose Sabina diagnostic used through /test-store.
    Activate with query prefix __DIAG__ so normal searches are untouched.
    """
    real_query = clean(str(query or "").replace("__DIAG__", "", 1))
    started = __import__("time").monotonic()
    report = {
        "diagnostic": "sabina",
        "query": real_query,
        "module": {
            "BASE_URL": BASE_URL,
            "BASE": globals().get("BASE"),
            "_clean": callable(globals().get("_clean")),
            "search": callable(globals().get("search")),
            "search_stream": callable(globals().get("search_stream")),
        },
        "routes": [],
        "candidate_urls": [],
        "products": [],
        "error": None,
    }
    session = requests.Session()
    try:
        encoded = __import__("urllib.parse", fromlist=["quote_plus"]).quote_plus(real_query)
        routes = (
            f"{BASE_URL}/es/buscar?search_query={encoded}",
            f"{BASE_URL}/es/buscar?s={encoded}",
            f"{BASE_URL}/it/ricerca?search_query={encoded}",
            f"{BASE_URL}/it/ricerca_old?s={encoded}",
        )
        seen = set()
        for route in routes:
            item = {"url": route}
            try:
                r = session.get(route, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                item.update({"status_code": r.status_code, "final_url": r.url, "html_bytes": len(r.content or b"")})
                if r.status_code < 400:
                    soup = BeautifulSoup(r.text or "", "html.parser")
                    found = []
                    for a in soup.find_all("a", href=True):
                        u = normalise_url(a.get("href"), r.url)
                        if u and is_product_url(u) and u not in seen and query_matches(a.get_text(" ", strip=True) + " " + u, real_query):
                            seen.add(u); found.append(u)
                    item["product_links"] = len(found)
                    item["sample_product_urls"] = found[:8]
                    report["candidate_urls"].extend(found)
                else:
                    item["product_links"] = 0
            except Exception as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"
            report["routes"].append(item)
            if len(report["candidate_urls"]) >= MAX_CANDIDATES:
                break

        report["candidate_urls"] = list(dict.fromkeys(report["candidate_urls"]))[:MAX_CANDIDATES]

        for url in report["candidate_urls"][:4]:
            product_report = {"url": url}
            try:
                r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
                product_report["status_code"] = r.status_code
                product_report["final_url"] = r.url
                product_report["html_bytes"] = len(r.content or b"")
                if r.status_code < 400:
                    soup = BeautifulSoup(r.text or "", "html.parser")
                    product = first_jsonld_product(soup)
                    product_report["jsonld_product"] = bool(product)
                    product_report["jsonld_name"] = (product or {}).get("name") if isinstance(product, dict) else None
                    product_report["jsonld_offers"] = (product or {}).get("offers") if isinstance(product, dict) else None
                    product_report["h1"] = clean((soup.find("h1").get_text(" ", strip=True) if soup.find("h1") else ""))
                    product_report["parsed_query_match"] = query_matches(product_report["jsonld_name"] or product_report["h1"] or url, real_query)
                    product_report["size_ml"] = extract_size_ml_from_product_page(soup, product_report["jsonld_name"] or product_report["h1"])
                    product_report["html_price"] = extract_price_from_html(soup)[0]
                    product_report["variants"] = extract_variant_offers_from_page(soup)[:10]
                else:
                    product_report["error"] = f"HTTP {r.status_code}"
            except Exception as exc:
                product_report["error"] = f"{type(exc).__name__}: {exc}"
            report["products"].append(product_report)
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        session.close()
    report["elapsed"] = round(__import__("time").monotonic() - started, 3)
    return [report]

def search_stream(query, emit):
    query = clean(query)
    if not query:
        return None
    started = __import__("time").monotonic()
    discovery_session = requests.Session()
    try:
        candidate_urls = discover_product_urls(discovery_session, query)
    finally:
        discovery_session.close()
    discovery_elapsed = round(__import__("time").monotonic() - started, 3)
    if not candidate_urls:
        return None
    seen = set()
    with ThreadPoolExecutor(max_workers=min(PRODUCT_WORKERS, len(candidate_urls))) as pool:
        futures = [pool.submit(_fetch_product, url, query) for url in candidate_urls]
        for future in as_completed(futures):
            try:
                product = future.result()
            except Exception:
                product = None
            if not product:
                continue
            raw_variants = (product.get("raw_data") or {}).get("variant_offers") or []
            rows = []
            if raw_variants:
                for variant in raw_variants:
                    size = variant.get("size_ml")
                    price = variant.get("price")
                    if size is None or price is None:
                        continue
                    item = dict(product)
                    item["price"] = f"{float(price):.2f}".replace(".", ",") + " €"
                    item["offer"] = dict(product.get("offer") or {})
                    item["offer"]["price"] = float(price)
                    item["offer"]["currency"] = variant.get("currency", "EUR")
                    item.setdefault("attributes", {})["size_ml"] = {"value": size, "source": "product_page_variant"}
                    key = (item.get("url"), size, round(float(price), 2))
                    if key not in seen:
                        seen.add(key)
                        rows.append(item)
            else:
                key = product.get("identity", {}).get("store_product_id", {}).get("value") or product.get("url")
                if key not in seen:
                    seen.add(key)
                    rows.append(product)
            for row in rows:
                row["_diagnostic_discovery_elapsed"] = discovery_elapsed
                row["_diagnostic_first_result_elapsed"] = round(__import__("time").monotonic() - started, 3)
                emit(row)
    return None


def search(query):
    if str(query or "").startswith("__DIAG__"):
        return diagnostic_search(query)

    query = clean(query)
    if not query:
        return []

    discovery_session = requests.Session()
    try:
        candidate_urls = discover_product_urls(discovery_session, query)
    finally:
        discovery_session.close()

    if not candidate_urls:
        return []

    results = []
    seen = set()

    # Product pages are independent. Fetch them in parallel so one slow/bocked
    # Sabina page cannot consume the whole Render job and starve other stores.
    with ThreadPoolExecutor(max_workers=min(PRODUCT_WORKERS, len(candidate_urls))) as pool:
        futures = {pool.submit(_fetch_product, url, query): url for url in candidate_urls}
        for future in as_completed(futures):
            product = future.result()
            if not product:
                continue

            raw_variants = (product.get("raw_data") or {}).get("variant_offers") or []
            if raw_variants:
                for variant in raw_variants:
                    variant_size = variant.get("size_ml")
                    variant_price = variant.get("price")
                    if variant_size is None or variant_price is None:
                        continue
                    item = dict(product)
                    item["name"] = product.get("name") or query
                    item["price"] = f"{float(variant_price):.2f}".replace(".", ",") + " €"
                    item["offer"] = dict(product.get("offer") or {})
                    item["offer"]["price"] = float(variant_price)
                    item["offer"]["currency"] = variant.get("currency", "EUR")
                    item.setdefault("attributes", {})["size_ml"] = {
                        "value": variant_size,
                        "source": "product_page_variant",
                    }
                    key = (item.get("url"), variant_size, round(float(variant_price), 2))
                    if key not in seen:
                        seen.add(key)
                        results.append(item)
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

# Temporary diagnostic endpoint for live Sabina discovery.
# It is registered only when this scraper is imported by the running FastAPI app.
def _register_sabina_diagnostic_route():
    try:
        import sys
        main_module = sys.modules.get("main")
        app = getattr(main_module, "app", None) if main_module else None
        if app is None or getattr(app.state, "_sabina_diag_registered", False):
            return

        @app.get("/diagnose-sabina")
        def diagnose_sabina(q: str = "Liquid Brun"):
            import time as _time
            from urllib.parse import quote_plus as _quote_plus
            report = {
                "ok": True,
                "query": q,
                "module": __name__,
                "attributes": {
                    "BASE_URL": globals().get("BASE_URL"),
                    "BASE": globals().get("BASE"),
                    "_clean": callable(globals().get("_clean")),
                    "search": callable(globals().get("search")),
                    "search_stream": callable(globals().get("search_stream")),
                },
                "endpoints": [],
                "products": [],
            }
            endpoints = (
                f"{globals().get('BASE_URL', 'https://www.sabina.com')}/en/search?controller=search&s={_quote_plus(q)}",
                f"{globals().get('BASE_URL', 'https://www.sabina.com')}/en/search?s={_quote_plus(q)}",
                f"{globals().get('BASE_URL', 'https://www.sabina.com')}/en/search?query={_quote_plus(q)}",
                f"{globals().get('BASE_URL', 'https://www.sabina.com')}/en/?s={_quote_plus(q)}",
            )
            for endpoint in endpoints:
                started = _time.monotonic()
                item = {"url": endpoint}
                try:
                    session = requests.Session()
                    session.headers.update(HEADERS)
                    response = session.get(endpoint, timeout=(3, 8), allow_redirects=True)
                    soup = BeautifulSoup(response.text, "html.parser")
                    found = []
                    seen = set()
                    for a in soup.select("a[href]"):
                        url = globals()["normalise_url"](a.get("href"))
                        if not url or not globals()["is_product_url"](url) or url in seen:
                            continue
                        text = a.get_text(" ", strip=True)
                        if globals()["query_matches"](f"{text} {url}", q):
                            seen.add(url)
                            found.append({"url": url, "text": text[:200]})
                    item.update({
                        "status_code": response.status_code,
                        "final_url": response.url,
                        "elapsed": round(_time.monotonic() - started, 3),
                        "html_length": len(response.text),
                        "title": soup.title.get_text(" ", strip=True) if soup.title else "",
                        "matching_product_links": found[:10],
                        "matching_count": len(found),
                    })
                except Exception as exc:
                    item.update({"elapsed": round(_time.monotonic() - started, 3), "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    try: session.close()
                    except Exception: pass
                report["endpoints"].append(item)

            product_urls = []
            for endpoint in report["endpoints"]:
                for found in endpoint.get("matching_product_links", []):
                    url = found.get("url")
                    if url and url not in product_urls:
                        product_urls.append(url)
            for url in product_urls[:5]:
                started = _time.monotonic()
                item = {"url": url}
                try:
                    session = requests.Session()
                    session.headers.update(HEADERS)
                    response = session.get(url, timeout=(3, 8), allow_redirects=True)
                    soup = BeautifulSoup(response.text, "html.parser")
                    jsonld = []
                    for script in soup.select('script[type="application/ld+json"]'):
                        raw = script.string or script.get_text()
                        if raw:
                            try:
                                jsonld.append(json.loads(raw))
                            except Exception:
                                pass
                    product = globals()["first_jsonld_product"](soup)
                    name = str(product.get("name") or "") if isinstance(product, dict) else ""
                    price = None
                    if isinstance(product, dict):
                        offers = product.get("offers")
                        offer = offers if isinstance(offers, dict) else (offers[0] if isinstance(offers, list) and offers else {})
                        if isinstance(offer, dict): price = offer.get("price")
                    item.update({
                        "status_code": response.status_code,
                        "elapsed": round(_time.monotonic() - started, 3),
                        "html_length": len(response.text),
                        "page_title": soup.title.get_text(" ", strip=True) if soup.title else "",
                        "jsonld_blocks": len(jsonld),
                        "jsonld_product_found": bool(product),
                        "product_name": name,
                        "query_matches_name": globals()["query_matches"](name or url, q),
                        "jsonld_price": price,
                        "parser_result": globals()["_sabina_parse_product"](response.text, url, q),
                    })
                except Exception as exc:
                    item.update({"elapsed": round(_time.monotonic() - started, 3), "error": f"{type(exc).__name__}: {exc}"})
                finally:
                    try: session.close()
                    except Exception: pass
                report["products"].append(item)
            return report

        app.state._sabina_diag_registered = True
    except Exception:
        pass


_register_sabina_diagnostic_route()
