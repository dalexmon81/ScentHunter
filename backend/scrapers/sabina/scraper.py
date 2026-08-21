import json
import re
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
SEARCH_URL = BASE_URL + "/es/buscar"
TIMEOUT = 10
MAX_CANDIDATES = 20

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
    """
    The only primary discovery path used by the real scraper.

    The query is supplied at runtime. No product, brand, SKU or URL
    is hard-coded here.
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

    def add(raw):
        absolute = normalise_url(
            raw,
            response.url,
        )

        if not absolute:
            return

        if not is_product_url(absolute):
            return

        if absolute in seen:
            return

        seen.add(absolute)
        urls.append(absolute)

    # First source: normal product links.
    for anchor in soup.find_all(
        "a",
        href=True,
    ):
        add(anchor.get("href"))

    # Second source: product URLs embedded in the returned HTML/JSON.
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
            product = extract_product_page(
                session,
                url,
                query,
            )

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
