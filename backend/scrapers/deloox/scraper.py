"""
ScentHunter - Deloox scraper
Version: fast independent adapter

Principi:
- requests + BeautifulSoup, nessun Playwright
- Deloox internal search come percorso primario
- discovery limitata e bounded
- product pages recuperate IN PARALLELO
- niente sitemap durante la ricerca live
- varianti size/price associate solo quando appartengono allo stesso
  blocco DOM o allo stesso structured-data offer
- gli out-of-stock non vengono eliminati
- nessun prezzo inventato
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.com"

# Timeout volutamente corto: l'orchestratore principale ha già una deadline
# globale e non deve essere rallentato da Deloox.
CONNECT_TIMEOUT = 2.5
READ_TIMEOUT = 5.0
TIMEOUT = (CONNECT_TIMEOUT, READ_TIMEOUT)

MAX_CANDIDATES = 16
MAX_RESULTS = 40
PRODUCT_WORKERS = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
}


# ---------------------------------------------------------------------------
# TEXT / IDENTITY HELPERS
# ---------------------------------------------------------------------------

def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value) -> str:
    text = clean(value).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def tokens(value):
    return {
        token
        for token in norm(value).split()
        if len(token) > 1
    }


def query_matches(text, query) -> bool:
    q_tokens = tokens(query)
    if not q_tokens:
        return False

    haystack = tokens(text)
    return q_tokens.issubset(haystack)


def size_ml(*values):
    text = " ".join(clean(value) for value in values if value)
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
        re.I,
    )
    if not match:
        return None

    number = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        number *= 10

    return int(number) if number.is_integer() else number


def concentration(*values):
    text = norm(" ".join(clean(value) for value in values))

    if re.search(r"\beau de toilette\b|\bedt\b", text):
        return "Eau de Toilette"

    if re.search(r"\beau de parfum\b|\bedp\b", text):
        return "Eau de Parfum"

    if re.search(r"\bextrait(?: de parfum)?\b", text):
        return "Extrait de Parfum"

    if re.search(r"\bparfum\b|\bperfume\b", text):
        return "Parfum"

    return None


def parse_price(value):
    if value is None:
        return None

    text = clean(value)
    text = text.replace("\xa0", " ")

    # Supporta:
    # 39,95
    # 39.95
    # €39,95
    # 39,95 €
    match = re.search(
        r"(?:€\s*)?(\d{1,4}(?:[.,]\d{1,2})?)(?:\s*€)?",
        text,
    )
    if not match:
        return None

    try:
        price = float(match.group(1).replace(",", "."))
    except ValueError:
        return None

    if price <= 0 or price > 10000:
        return None

    return round(price, 2)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update(HEADERS)
    return session


def _get(session, url):
    try:
        response = session.get(
            url,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if response.status_code >= 400:
        return None

    if not response.text:
        return None

    return response


# ---------------------------------------------------------------------------
# JSON-LD
# ---------------------------------------------------------------------------

def _jsonld_objects(soup):
    objects = []

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.get_text(strip=True)
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        queue = [data]

        while queue:
            item = queue.pop(0)

            if isinstance(item, list):
                queue.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            objects.append(item)

            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)

    return objects


def _product_jsonld(soup):
    for item in _jsonld_objects(soup):
        product_type = item.get("@type")

        if product_type == "Product":
            return item

        if isinstance(product_type, list) and "Product" in product_type:
            return item

        if "offers" in item and (
            item.get("name")
            or item.get("brand")
            or item.get("sku")
        ):
            return item

    return {}


def _offer_list(data):
    offers = data.get("offers")

    if isinstance(offers, dict):
        return [offers]

    if isinstance(offers, list):
        return [
            offer
            for offer in offers
            if isinstance(offer, dict)
        ]

    return []


# ---------------------------------------------------------------------------
# AVAILABILITY
# ---------------------------------------------------------------------------

def _availability_from_value(value):
    text = norm(value)

    if not text:
        return None

    if any(
        marker in text
        for marker in (
            "outofstock",
            "out of stock",
            "soldout",
            "sold out",
            "discontinued",
            "unavailable",
        )
    ):
        return False

    if any(
        marker in text
        for marker in (
            "instock",
            "in stock",
            "limitedavailability",
            "limited availability",
            "preorder",
            "pre order",
        )
    ):
        return True

    return None


def availability(soup, offer=None):
    # 1. JSON-LD: priorità massima.
    if isinstance(offer, dict):
        state = _availability_from_value(
            offer.get("availability")
            or offer.get("itemAvailability")
            or offer.get("availabilityStatus")
        )
        if state is not None:
            return state

    # 2. Solo elementi strettamente legati all'acquisto/disponibilità.
    selectors = [
        '[itemprop="availability"]',
        '[data-testid*="availability" i]',
        '[data-test*="availability" i]',
        '[class*="availability" i]',
        '[class*="stock" i]',
        '[class*="add-to-cart" i]',
        '[class*="buy" i]',
        'button[type="submit"]',
    ]

    scoped = []

    for selector in selectors:
        try:
            nodes = soup.select(selector)
        except Exception:
            nodes = []

        for node in nodes[:12]:
            text = clean(
                node.get("content")
                or node.get("aria-label")
                or node.get_text(" ", strip=True)
            )
            if text:
                scoped.append(text)

    if scoped:
        state = _availability_from_value(" ".join(scoped))
        if state is not None:
            return state

    # 3. Fallback limitato al testo vicino ai controlli.
    return None


# ---------------------------------------------------------------------------
# PRODUCT CANDIDATE DISCOVERY
# ---------------------------------------------------------------------------

def _is_product_url(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.netloc.lower() not in {
        "deloox.com",
        "www.deloox.com",
    }:
        return False

    path = parsed.path.lower()

    return "/product/" in path or "/produit/" in path


def _candidate_product_urls(html, query):
    """
    Discovery permissiva.

    NON richiediamo che tutti i token siano nello slug: Deloox può mettere
    il nome nel testo/JSON della card e usare uno slug numerico.
    """

    soup = BeautifulSoup(html, "html.parser")

    q_tokens = tokens(query)
    scored = {}

    def add(raw_url, context=""):
        if not raw_url:
            return

        raw_url = clean(raw_url).replace("\\/", "/")

        if raw_url.startswith(
            ("javascript:", "mailto:", "#")
        ):
            return

        url = urljoin(BASE_URL, raw_url)
        url = url.split("#", 1)[0]
        url = url.split("?", 1)[0]

        if not _is_product_url(url):
            return

        context_text = norm(
            f"{context} {url}"
        )

        hits = sum(
            1
            for token in q_tokens
            if token in context_text
        )

        # Discovery live deve restare stretta.
        if q_tokens and hits == 0:
            return

        old = scored.get(url)

        if old is None or hits > old[0]:
            scored[url] = (
                hits,
                clean(context),
            )

    # Link normali.
    for anchor in soup.find_all("a", href=True):
        add(
            anchor.get("href"),
            anchor.get_text(" ", strip=True),
        )

    # URL presenti in HTML/JS.
    patterns = [
        r'https?://(?:www\.)?deloox\.com/[^"\'>\s]+/(?:product|produit)/[^"\'>\s]+',
        r'["\']((?:/)?(?:en/|it/|nl/)?(?:product|produit)/[^"\']+)["\']',
        r'["\']((?:https?:)?//(?:www\.)?deloox\.com/[^"\']*/(?:product|produit)/[^"\']+)["\']',
    ]

    for pattern in patterns:
        for raw in re.findall(pattern, html, re.I):
            if isinstance(raw, tuple):
                raw = "".join(raw)
            add(raw)

    # Serialized cards: URL + product title nello stesso piccolo blocco.
    for tag in soup.find_all(
        ["article", "li", "div", "script"]
    ):
        blob = str(tag)

        if "/product/" not in blob.lower() and "/produit/" not in blob.lower():
            continue

        if len(blob) > 12000:
            continue

        urls = re.findall(
            r'(?:(?:https?:)?//(?:www\.)?deloox\.com)?'
            r'[^"\'<>\s]*?/(?:product|produit)/[^"\'<>\s]+',
            blob,
            re.I,
        )

        context = tag.get_text(
            " ",
            strip=True,
        )[:1200]

        for raw in urls:
            add(raw, context)

    ordered = sorted(
        scored.items(),
        key=lambda pair: (
            -pair[1][0],
            len(pair[0]),
            pair[0],
        ),
    )

    return [
        url
        for url, _meta in ordered
    ][:MAX_CANDIDATES]


def _search_endpoints(query):
    encoded = quote_plus(query)

    return [
        f"{BASE_URL}/en/search?query={encoded}",
        f"{BASE_URL}/en/search?q={encoded}",
        f"{BASE_URL}/en/search?search={encoded}",
    ]


def _discover_fast(session, query):
    """
    Solo ricerca interna Deloox.

    Niente sitemap nella richiesta utente.
    Niente crawling dell'intero catalogo.
    """

    seen = set()
    candidates = []

    for endpoint in _search_endpoints(query):
        response = _get(session, endpoint)

        if response is None:
            continue

        for url in _candidate_product_urls(
            response.text,
            query,
        ):
            if url in seen:
                continue

            seen.add(url)
            candidates.append(url)

            if len(candidates) >= MAX_CANDIDATES:
                return candidates

    return candidates


# ---------------------------------------------------------------------------
# CATEGORY FALLBACK
# ---------------------------------------------------------------------------

CATEGORY_URLS = (
    f"{BASE_URL}/category/1075660/womens-perfume.html",
    f"{BASE_URL}/category/1075750/mens-perfume.html",
)


def _discover_category_fallback(session, query):
    """
    Fallback leggero.

    Viene usato solo se la ricerca interna non produce candidati.
    Non viene usato il sitemap live.
    """

    candidates = []
    seen = set()

    for category_url in CATEGORY_URLS:
        response = _get(session, category_url)

        if response is None:
            continue

        urls = _candidate_product_urls(
            response.text,
            query,
        )

        for url in urls:
            if url in seen:
                continue

            seen.add(url)
            candidates.append(url)

            if len(candidates) >= MAX_CANDIDATES:
                return candidates

    return candidates


# ---------------------------------------------------------------------------
# VARIANT EXTRACTION
# ---------------------------------------------------------------------------

SIZE_RE = re.compile(
    r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
    re.I,
)


def _variant_blocks(soup):
    selectors = (
        "[class*='variant'], [class*='Variant'], "
        "[class*='option'], [class*='Option'], "
        "[class*='volume'], [class*='Volume'], "
        "[class*='size'], [class*='Size']"
    )

    try:
        nodes = soup.select(selectors)
    except Exception:
        return []

    blocks = []

    for node in nodes:
        text = clean(
            node.get_text(
                " ",
                strip=True,
            )
        )

        if not text or len(text) > 700:
            continue

        if not SIZE_RE.search(text):
            continue

        price = parse_price(text)

        if price is None:
            continue

        blocks.append(
            (node, text, price)
        )

    return blocks


def _extract_dom_variants(
    soup,
    product_name,
    product_url,
    default_available,
):
    results = []
    seen = set()

    # Metodo 1: blocchi locali.
    for _node, text, price in _variant_blocks(soup):
        matches = list(SIZE_RE.finditer(text))

        for match in matches:
            number = float(
                match.group(1).replace(",", ".")
            )

            if match.group(2).lower() == "cl":
                number *= 10

            size = (
                int(number)
                if number.is_integer()
                else number
            )

            key = (
                size,
                price,
                default_available,
            )

            if key in seen:
                continue

            seen.add(key)

            label = (
                f"{int(size)} ml"
                if float(size).is_integer()
                else f"{size} ml"
            )

            results.append(
                {
                    "store": STORE,
                    "brand": "",
                    "name": product_name,
                    "price": f"{price:.2f}".replace(".", ",") + " €",
                    "price_num": price,
                    "url": product_url,
                    "size": label,
                    "size_ml": size,
                    "available": default_available,
                    "availability": (
                        "in_stock"
                        if default_available is True
                        else (
                            "out_of_stock"
                            if default_available is False
                            else "unknown"
                        )
                    ),
                }
            )

    if results:
        return results

    # Metodo 2: da un testo "50 ml" risaliamo solo pochi parent,
    # evitando di associare il prezzo di una sezione enorme.
    for text_node in soup.find_all(
        string=SIZE_RE
    ):
        value = clean(text_node)

        if len(value) > 100:
            continue

        matches = list(SIZE_RE.finditer(value))

        if not matches:
            continue

        parent = text_node.parent

        for _ in range(4):
            if parent is None:
                break

            block = clean(
                parent.get_text(
                    " ",
                    strip=True,
                )
            )

            if len(block) <= 450:
                price = parse_price(block)

                if price is not None:
                    for match in matches:
                        number = float(
                            match.group(1).replace(",", ".")
                        )

                        if match.group(2).lower() == "cl":
                            number *= 10

                        size = (
                            int(number)
                            if number.is_integer()
                            else number
                        )

                        key = (
                            size,
                            price,
                            default_available,
                        )

                        if key in seen:
                            continue

                        seen.add(key)

                        label = (
                            f"{int(size)} ml"
                            if float(size).is_integer()
                            else f"{size} ml"
                        )

                        results.append(
                            {
                                "store": STORE,
                                "brand": "",
                                "name": product_name,
                                "price": (
                                    f"{price:.2f}".replace(".", ",")
                                    + " €"
                                ),
                                "price_num": price,
                                "url": product_url,
                                "size": label,
                                "size_ml": size,
                                "available": default_available,
                                "availability": (
                                    "in_stock"
                                    if default_available is True
                                    else (
                                        "out_of_stock"
                                        if default_available is False
                                        else "unknown"
                                    )
                                ),
                            }
                        )

                    break

            parent = parent.parent

    return results


# ---------------------------------------------------------------------------
# PRODUCT PARSER
# ---------------------------------------------------------------------------

def _product(url, html, query):
    soup = BeautifulSoup(
        html,
        "html.parser",
    )

    data = _product_jsonld(soup)

    h1 = soup.find("h1")

    name = clean(
        data.get("name")
    ) or (
        clean(h1.get_text(" ", strip=True))
        if h1
        else ""
    )

    if not name:
        return []

    # Il nome reale della pagina è l'autorità per il match finale.
    if not query_matches(name, query):
        return []

    brand = data.get("brand")

    if isinstance(brand, dict):
        brand = brand.get("name")

    brand = clean(brand)

    if not brand:
        # Solo fallback strutturato, non inventiamo il brand dal testo.
        meta_brand = soup.select_one(
            '[itemprop="brand"]'
        )

        if meta_brand:
            brand = clean(
                meta_brand.get("content")
                or meta_brand.get_text(
                    " ",
                    strip=True,
                )
            )

    offers = _offer_list(data)

    primary_offer = (
        offers[0]
        if offers
        else {}
    )

    offer_states = [
        _availability_from_value(
            offer.get("availability")
            or offer.get("itemAvailability")
            or offer.get("availabilityStatus")
        )
        for offer in offers
    ]

    offer_states = [
        state
        for state in offer_states
        if state is not None
    ]

    if True in offer_states:
        page_available = True
    elif False in offer_states:
        page_available = False
    else:
        page_available = availability(
            soup,
            primary_offer,
        )

    image = data.get("image")

    if isinstance(image, list):
        image = (
            image[0]
            if image
            else None
        )

    image = (
        urljoin(url, str(image))
        if image
        else None
    )

    gtin = clean(
        data.get("gtin13")
        or data.get("gtin")
        or ""
    ) or None

    mpn = clean(
        data.get("mpn")
        or ""
    ) or None

    sku = clean(
        data.get("sku")
        or ""
    ) or None

    product_concentration = concentration(
        name
    )

    # 1) Varianti DOM: size + prezzo nello stesso blocco.
    variants = _extract_dom_variants(
        soup,
        name,
        url,
        page_available,
    )

    if variants:
        for item in variants:
            item["brand"] = brand
            item["concentration"] = product_concentration
            item["image"] = image

            if sku:
                item["sku"] = sku
                item["store_product_id"] = sku

            if gtin:
                item["gtin"] = gtin

            if mpn:
                item["mpn"] = mpn

        return variants[:MAX_RESULTS]

    # 2) Structured-data offer.
    structured_results = []

    for offer in offers:
        currency = clean(
            offer.get("priceCurrency")
            or "EUR"
        ).upper()

        if currency and currency != "EUR":
            continue

        price = parse_price(
            offer.get("price")
            or offer.get("lowPrice")
        )

        state = _availability_from_value(
            offer.get("availability")
            or offer.get("itemAvailability")
            or offer.get("availabilityStatus")
        )

        if state is None:
            state = page_available

        offer_name = clean(
            offer.get("name")
            or ""
        )

        offer_size = size_ml(
            offer_name,
            name,
        )

        # Se l'offerta è esplicitamente out-of-stock senza prezzo,
        # la conserviamo.
        if price is None and state is not False:
            continue

        structured_results.append(
            {
                "store": STORE,
                "brand": brand,
                "name": name,
                "price": (
                    f"{price:.2f}".replace(".", ",") + " €"
                    if price is not None
                    else None
                ),
                "price_num": price,
                "url": url,
                "size_ml": offer_size,
                "size": (
                    f"{int(offer_size)} ml"
                    if offer_size is not None
                    and float(offer_size).is_integer()
                    else (
                        f"{offer_size} ml"
                        if offer_size is not None
                        else None
                    )
                ),
                "available": state,
                "availability": (
                    "in_stock"
                    if state is True
                    else (
                        "out_of_stock"
                        if state is False
                        else "unknown"
                    )
                ),
                "concentration": product_concentration,
                "image": image,
                "sku": sku,
                "store_product_id": sku,
                "gtin": gtin,
                "mpn": mpn,
            }
        )

    if structured_results:
        return structured_results[:MAX_RESULTS]

    # 3) Fallback prodotto singolo.
    # Prima JSON-LD, poi solo elementi di prezzo della pagina.
    price = parse_price(
        primary_offer.get("price")
    )

    if price is None:
        price_nodes = soup.select(
            '[itemprop="price"], '
            '[data-testid*="price" i], '
            '[class*="price" i]'
        )

        for node in price_nodes[:20]:
            price = parse_price(
                node.get("content")
                or node.get_text(
                    " ",
                    strip=True,
                )
            )

            if price is not None:
                break

    # Un out-of-stock senza prezzo resta comunque visibile.
    if price is None and page_available is not False:
        return []

    selected_size = size_ml(name)

    return [
        {
            "store": STORE,
            "brand": brand,
            "name": name,
            "price": (
                f"{price:.2f}".replace(".", ",") + " €"
                if price is not None
                else None
            ),
            "price_num": price,
            "url": url,
            "size_ml": selected_size,
            "size": (
                f"{int(selected_size)} ml"
                if selected_size is not None
                and float(selected_size).is_integer()
                else (
                    f"{selected_size} ml"
                    if selected_size is not None
                    else None
                )
            ),
            "available": page_available,
            "availability": (
                "in_stock"
                if page_available is True
                else (
                    "out_of_stock"
                    if page_available is False
                    else "unknown"
                )
            ),
            "concentration": product_concentration,
            "image": image,
            "sku": sku,
            "store_product_id": sku,
            "gtin": gtin,
            "mpn": mpn,
        }
    ]


# ---------------------------------------------------------------------------
# PUBLIC SEARCH
# ---------------------------------------------------------------------------

def search(query):
    query = clean(query)

    if not query:
        return []

    session = _session()

    try:
        # FAST PATH ----------------------------------------------------------
        candidates = _discover_fast(
            session,
            query,
        )

        # LIGHT FALLBACK ----------------------------------------------------
        if not candidates:
            candidates = _discover_category_fallback(
                session,
                query,
            )

        if not candidates:
            return []

        candidates = candidates[:MAX_CANDIDATES]

        results = []
        seen = set()

        # Recuperiamo le pagine prodotto IN PARALLELO.
        with ThreadPoolExecutor(
            max_workers=min(
                PRODUCT_WORKERS,
                len(candidates),
            )
        ) as executor:
            futures = {
                executor.submit(
                    _fetch_and_parse,
                    url,
                    query,
                ): url
                for url in candidates
            }

            for future in as_completed(futures):
                url = futures[future]

                try:
                    items = future.result()
                except Exception:
                    continue

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    key = (
                        item.get("url", ""),
                        item.get("size_ml"),
                        item.get("price_num"),
                        item.get("available"),
                    )

                    if key in seen:
                        continue

                    seen.add(key)
                    results.append(item)

        # Prezzo disponibile prima, out-of-stock per ultimi.
        def sort_key(item):
            available = item.get("available")
            price = item.get("price_num")

            if available is False:
                rank = 2
            elif price is not None:
                rank = 0
            else:
                rank = 1

            try:
                numeric_price = float(price)
            except (TypeError, ValueError):
                numeric_price = float("inf")

            return (
                rank,
                numeric_price,
                float(item.get("size_ml") or 99999),
            )

        results.sort(key=sort_key)

        return results[:MAX_RESULTS]

    finally:
        session.close()


def _fetch_and_parse(url, query):
    session = _session()

    try:
        response = _get(
            session,
            url,
        )

        if response is None:
            return []

        return _product(
            response.url.split("#", 1)[0],
            response.text,
            query,
        )
    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "query",
        nargs="+",
    )

    args = parser.parse_args()
    query = " ".join(args.query)

    print(
        json.dumps(
            search(query),
            ensure_ascii=False,
            indent=2,
        )
    )
