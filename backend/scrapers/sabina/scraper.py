from __future__ import annotations

import json
import logging
import os
import re
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception
    sync_playwright = None


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
SEARCH_URL = BASE_URL + "/es/buscar_old?s={query}"
TIMEOUT = int(os.getenv("SABINA_TIMEOUT_S", "20"))
BROWSER_TIMEOUT_MS = int(os.getenv("SABINA_BROWSER_TIMEOUT_MS", "30000"))
BROWSER_ENABLED = os.getenv("SABINA_BROWSER", "1").lower() not in {
    "0", "false", "no"
}

LOGGER = logging.getLogger(__name__)

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
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# Generic Sabina product URL:
# locale / arbitrary category path / numeric-id-slug.html
PRODUCT_URL_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl)/.+/(\d+)-[^/]+\.html$",
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "by", "ml", "pour",
}

NON_PRODUCT_TERMS = {
    "gift set", "set regalo", "coffret", "bundle", "kit",
    "deodorant", "deo spray", "shower gel", "body lotion",
    "after shave", "aftershave", "travel set", "discovery set",
    "body mist", "hand cream", "handcreme",
}

PACKAGING_RULES = (
    ("gift_set", ("gift set", "set regalo", "coffret", "gift box")),
    ("discovery_set", ("discovery set", "discoveryset")),
    ("bundle", ("bundle", "duo", "trio", "pack")),
    ("tester", ("tester",)),
    ("sample", ("sample", "muestra", "échantillon", "campione")),
    ("decant", ("decant",)),
)

CONCENTRATION_RULES = (
    ("Extrait de Parfum", (
        r"\bextrait\s+(?:de\s+)?parfum\b", r"\bextrait\b"
    )),
    ("Eau de Parfum", (
        r"\beau\s+de\s+parfum\b", r"\bedp\b"
    )),
    ("Eau de Toilette", (
        r"\beau\s+de\s+toilette\b", r"\bedt\b"
    )),
    ("Eau de Cologne", (
        r"\beau\s+de\s+cologne\b", r"\bedc\b"
    )),
    ("Parfum", (r"\bparfum\b",)),
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
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
        token for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def query_matches(text, query):
    tokens = query_tokens(query)
    normalized = norm(text)
    return bool(tokens) and all(token in normalized for token in tokens)


def is_product_url(url):
    return bool(PRODUCT_URL_RE.match(urlparse(url).path))


def product_id_from_url(url):
    match = PRODUCT_URL_RE.match(urlparse(url).path)
    return match.group(1) if match else None


def money_to_float(value):
    if value in (None, ""):
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    text = re.sub(r"[^\d,.\-]", "", text)

    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")

    try:
        return float(text)
    except ValueError:
        return None


def extract_size_ml(*texts):
    combined = " ".join(str(x or "") for x in texts)
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(?:ml|millilitros?|milliliters?)\b",
        combined,
        re.I,
    )
    if not match:
        return None

    value = float(match.group(1).replace(",", "."))
    return int(value) if value.is_integer() else value


def extract_concentration(*texts):
    normalized = norm(" ".join(str(x or "") for x in texts))

    for label, patterns in CONCENTRATION_RULES:
        for pattern in patterns:
            if re.search(pattern, normalized, re.I):
                return label, "product_text"

    return None, None


def extract_gender(*texts):
    normalized = norm(" ".join(str(x or "") for x in texts))

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


def extract_packaging_type(*texts):
    normalized = norm(" ".join(str(x or "") for x in texts))

    for packaging_type, terms in PACKAGING_RULES:
        for term in terms:
            if re.search(
                r"\b" + re.escape(norm(term)) + r"\b",
                normalized,
            ):
                return packaging_type, "product_text"

    return "product", "default"


def first_jsonld_product(soup):
    for script in soup.select(
        'script[type="application/ld+json"]'
    ):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            if item.get("@graph"):
                stack.extend(item["@graph"])

            item_type = item.get("@type")
            types = (
                item_type
                if isinstance(item_type, list)
                else [item_type]
            )

            if any(
                str(t).lower() == "product"
                for t in types
            ):
                return item

    return None


def extract_product_from_html(html, final_url):
    soup = BeautifulSoup(html, "html.parser")
    product = first_jsonld_product(soup)

    h1 = soup.select_one("h1")
    title = clean(
        (product or {}).get("name")
        or (h1.get_text(" ", strip=True) if h1 else "")
    )

    if not title:
        return None

    brand = None
    if isinstance((product or {}).get("brand"), dict):
        brand = clean((product["brand"].get("name")))
    elif (product or {}).get("brand"):
        brand = clean(product["brand"])

    sku = clean((product or {}).get("sku")) or None
    mpn = clean((product or {}).get("mpn")) or None

    gtin = clean(
        (product or {}).get("gtin13")
        or (product or {}).get("gtin12")
        or (product or {}).get("gtin14")
        or (product or {}).get("gtin")
    ) or None

    image = (product or {}).get("image")

    if isinstance(image, list):
        image = image[0] if image else None

    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")

    image = urljoin(final_url, image) if image else None

    offers = (product or {}).get("offers")

    if isinstance(offers, list):
        offer = offers[0] if offers else {}
    elif isinstance(offers, dict):
        offer = offers
    else:
        offer = {}

    price = money_to_float(offer.get("price"))
    currency = clean(offer.get("priceCurrency")) or "EUR"

    availability_raw = clean(
        offer.get("availability")
    ).lower()

    if "instock" in availability_raw:
        availability = "in_stock"
    elif (
        "outofstock" in availability_raw
        or "soldout" in availability_raw
    ):
        availability = "out_of_stock"
    elif "preorder" in availability_raw:
        availability = "preorder"
    else:
        page_text = norm(
            soup.get_text(" ", strip=True)
        )

        if (
            "fecha de disponibilidad" in page_text
            or "date de disponibilite" in page_text
        ):
            availability = "out_of_stock"
        else:
            availability = "unknown"

    page_text = soup.get_text(" ", strip=True)

    size_ml = extract_size_ml(
        title,
        page_text,
    )

    concentration, concentration_source = extract_concentration(
        title,
        page_text,
    )

    gender, gender_source = extract_gender(
        title,
        page_text,
    )

    packaging_type, packaging_source = extract_packaging_type(
        title,
        page_text,
    )

    if not sku:
        ref_match = re.search(
            r"(?:referencia|reference|référence|riferimento)"
            r"\s*[:#]?\s*([A-Z0-9_-]+)",
            page_text,
            re.I,
        )

        if ref_match:
            sku = ref_match.group(1)

    product_id = product_id_from_url(final_url)

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
                {"value": gtin, "source": "sabina_jsonld"}
                if gtin else None
            ),
            "mpn": (
                {"value": mpn, "source": "sabina_jsonld"}
                if mpn else None
            ),
            "sku": (
                {
                    "value": sku,
                    "source": "sabina_jsonld_or_reference",
                }
                if sku else None
            ),
            "store_product_id": (
                {
                    "value": product_id,
                    "source": "product_url",
                }
                if product_id else None
            ),
        },
        "attributes": {
            "size_ml": (
                {
                    "value": size_ml,
                    "source": "product_text",
                }
                if size_ml is not None else None
            ),
            "concentration": (
                {
                    "value": concentration,
                    "source": concentration_source,
                }
                if concentration else None
            ),
            "gender": (
                {
                    "value": gender,
                    "source": gender_source,
                }
                if gender_source else {
                    "value": "unknown",
                    "source": "default",
                }
            ),
            "packaging_type": {
                "value": packaging_type,
                "source": packaging_source,
            },
        },
        "offer": {
            "price": price,
            "currency": currency,
            "availability": availability,
        },
        "provenance": {
            "name": "sabina_jsonld_or_h1",
            "brand": "sabina_jsonld" if brand else None,
            "price": "sabina_jsonld",
            "availability": "sabina_jsonld_or_page_text",
            "image": "sabina_jsonld" if image else None,
            "store_product_id": (
                "product_url" if product_id else None
            ),
            "sku": (
                "sabina_jsonld_or_reference"
                if sku else None
            ),
            "gtin": "sabina_jsonld" if gtin else None,
            "mpn": "sabina_jsonld" if mpn else None,
            "size_ml": (
                "product_text"
                if size_ml is not None else None
            ),
            "concentration": concentration_source,
            "gender": gender_source,
            "packaging_type": packaging_source,
        },
        "raw_data": {
            "url": final_url,
            "jsonld_product": product,
        },
        "name": title,
        "brand": brand,
        "price": (
            f"{price:.2f}".replace(".", ",") + " €"
            if price is not None else ""
        ),
        "url": final_url,
        "available": availability == "in_stock",
    }


def discover_urls_requests(session, query):
    """Cheap first pass. It does not decide that the search failed."""
    urls = []
    seen = set()

    search_urls = (
        BASE_URL
        + "/es/buscar_old?s="
        + quote_plus(query),
        BASE_URL
        + "/es/buscar?controller=search&s="
        + quote_plus(query),
        BASE_URL
        + "/es/buscar?s="
        + quote_plus(query),
    )

    for search_url in search_urls:
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
            continue

        soup = BeautifulSoup(
            response.text,
            "html.parser",
        )

        for anchor in soup.find_all("a", href=True):
            absolute = urljoin(
                response.url,
                anchor["href"],
            ).split("#")[0]

            if not is_product_url(absolute):
                continue

            if absolute not in seen:
                seen.add(absolute)
                urls.append(absolute)

    return urls


def discover_urls_browser(query):
    """
    Browser fallback modelled on the working Notino strategy.

    The important difference from the old Sabina scraper is that the search
    page is allowed to execute its JavaScript before product links are read.
    Discovery remains structural: any Sabina product URL is a candidate.
    The product page performs the final query validation.
    """
    if not BROWSER_ENABLED or sync_playwright is None:
        LOGGER.warning(
            "SABINA_BROWSER: unavailable "
            "(Playwright import/runtime missing)"
        )
        return []

    search_url = SEARCH_URL.format(
        query=quote_plus(query)
    )

    found = []
    seen = set()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
            )

            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="es-ES",
                extra_http_headers={
                    "Accept-Language": HEADERS[
                        "Accept-Language"
                    ],
                },
            )

            page = context.new_page()

            LOGGER.info(
                "SABINA_BROWSER: GET %s",
                search_url,
            )

            page.goto(
                search_url,
                wait_until="domcontentloaded",
                timeout=BROWSER_TIMEOUT_MS,
            )

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=10000,
                )
            except PlaywrightTimeoutError:
                pass

            # Give delayed search-result rendering a short, generic window.
            try:
                page.wait_for_timeout(2500)
            except Exception:
                pass

            hrefs = page.locator(
                "a[href]"
            ).evaluate_all(
                """
                anchors => anchors.map(a => ({
                    href: a.href || "",
                    text: (a.innerText || a.textContent || ""),
                    title: a.getAttribute("title") || "",
                    aria: a.getAttribute("aria-label") || ""
                }))
                """
            )

            # Also inspect the final rendered HTML. Some product links can be
            # present in script-generated markup without useful anchor text.
            rendered_html = page.content()

            for item in hrefs:
                raw_url = clean(
                    item.get("href")
                )

                if not raw_url:
                    continue

                absolute = urljoin(
                    page.url,
                    raw_url,
                ).split("#")[0]

                if not is_product_url(absolute):
                    continue

                if absolute not in seen:
                    seen.add(absolute)
                    found.append(absolute)

            # Generic structural extraction from rendered HTML.
            for match in re.finditer(
                r"""(?:href=["'])([^"']+)""",
                rendered_html,
                re.I,
            ):
                absolute = urljoin(
                    page.url,
                    match.group(1),
                ).split("#")[0]

                if not is_product_url(absolute):
                    continue

                if absolute not in seen:
                    seen.add(absolute)
                    found.append(absolute)

            context.close()
            browser.close()

    except Exception as exc:
        LOGGER.exception(
            "SABINA_BROWSER: failed: %s",
            exc,
        )

    LOGGER.info(
        "SABINA_BROWSER: candidates=%s",
        len(found),
    )

    return found


def fetch_product_requests(session, url):
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

    return response


def fetch_product_browser(url):
    """Browser validation fallback when requests gets an incomplete page."""
    if not BROWSER_ENABLED or sync_playwright is None:
        return None

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
            )

            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale="es-ES",
            )

            page = context.new_page()

            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=BROWSER_TIMEOUT_MS,
            )

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=10000,
                )
            except PlaywrightTimeoutError:
                pass

            try:
                page.wait_for_timeout(1000)
            except Exception:
                pass

            html = page.content()
            final_url = page.url

            context.close()
            browser.close()

            return html, final_url

    except Exception as exc:
        LOGGER.exception(
            "SABINA_BROWSER_PRODUCT: failed %s: %s",
            url,
            exc,
        )
        return None


def validate_candidate(session, url, query):
    """
    Discovery is intentionally broad. Validation is strict and generic.

    A candidate survives only if the actual product page name contains all
    meaningful query tokens. This prevents unrelated recommendations/cards
    from entering ScentHunter.
    """
    response = fetch_product_requests(
        session,
        url,
    )

    if response is not None:
        product = extract_product_from_html(
            response.text,
            response.url,
        )

        if (
            product
            and query_matches(
                product.get("name", ""),
                query,
            )
        ):
            return product

    browser_result = fetch_product_browser(url)

    if browser_result is None:
        return None

    html, final_url = browser_result

    product = extract_product_from_html(
        html,
        final_url,
    )

    if (
        product
        and query_matches(
            product.get("name", ""),
            query,
        )
    ):
        return product

    return None


def search(query):
    query = clean(query)

    if not query:
        return []

    LOGGER.info(
        "SABINA_SEARCH: START query=%r",
        query,
    )

    session = requests.Session()

    try:
        session.get(
            BASE_URL + "/es/",
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        pass

    # First use cheap HTTP discovery.
    candidate_urls = discover_urls_requests(
        session,
        query,
    )

    LOGGER.info(
        "SABINA_SEARCH: requests_candidates=%s",
        len(candidate_urls),
    )

    # If the search result is client-rendered, switch to the same browser
    # fallback model already used successfully by Notino.
    if not candidate_urls:
        candidate_urls = discover_urls_browser(
            query,
        )

    LOGGER.info(
        "SABINA_SEARCH: browser_or_total_candidates=%s",
        len(candidate_urls),
    )

    results = []
    seen_products = set()

    # A search page can contain many unrelated product links. Validate every
    # candidate up to a safe generic ceiling.
    for url in candidate_urls[:30]:
        product = validate_candidate(
            session,
            url,
            query,
        )

        if not product:
            continue

        key = (
            product.get("identity", {})
            .get("store_product_id", {})
            .get("value")
        )

        key = key or product.get("url")

        if key in seen_products:
            continue

        packaging = (
            product.get("attributes", {})
            .get("packaging_type")
            or {}
        )

        packaging_value = (
            packaging.get("value")
            if isinstance(packaging, dict)
            else packaging
        )

        if packaging_value == "tester":
            continue

        # Keep the generic exclusion only for obvious accessory/set results.
        name_normalized = norm(
            product.get("name", "")
        )

        if any(
            norm(term) in name_normalized
            for term in NON_PRODUCT_TERMS
        ):
            continue

        seen_products.add(key)
        results.append(product)

    LOGGER.info(
        "SABINA_SEARCH: END query=%r results=%s",
        query,
        len(results),
    )

    return results


def scrape(query):
    return search(query)


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
