import json
import re
import html as html_lib
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 15

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Referer": BASE + "/it/",
}

IGNORED_PATHS = {
    "content", "ricerca", "ricerca_old", "marchi", "negozi", "contatto",
    "faq", "carrello", "ordine", "stato-ordine", "il-mio-conto",
    "module", "login", "registrazione", "wishlist",
}

PRICE_RE = re.compile(
    r"(?:€|EUR)\s*(\d{1,4}(?:[.,]\d{2}))"
    r"|(\d{1,4}(?:[.,]\d{2}))\s*(?:€|EUR)",
    re.I,
)


def _clean(value):
    return re.sub(
        r"\s+",
        " ",
        html_lib.unescape(str(value or "")),
    ).strip()


def _norm(value):
    value = _clean(value).lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def _tokens(value):
    return [x for x in _norm(value).split() if len(x) > 1]


def _matches(text, query):
    q = set(_tokens(query))
    if not q:
        return False
    return q.issubset(set(_tokens(text)))


def _price(value):
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    text = _clean(value)

    if re.fullmatch(r"\d+(?:[.,]\d{1,2})?", text):
        return float(text.replace(",", "."))

    match = PRICE_RE.search(text)
    if not match:
        return None

    raw = next((x for x in match.groups() if x), None)
    return float(raw.replace(",", ".")) if raw else None


def _size_ml(*values):
    text = " ".join(_clean(x) for x in values)
    match = re.search(
        r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl)\b",
        text,
        re.I,
    )
    if not match:
        return None

    value = float(match.group(1).replace(",", "."))
    if match.group(2).lower() == "cl":
        value *= 10

    return int(value) if value.is_integer() else value


def _concentration(*values):
    text = _norm(" ".join(_clean(x) for x in values))

    if re.search(r"\beau de toilette\b|\bedt\b", text):
        return "Eau de Toilette"
    if re.search(r"\beau de parfum\b|\bedp\b", text):
        return "Eau de Parfum"
    if re.search(r"\bextrait(?: de parfum)?\b", text):
        return "Extrait de Parfum"

    return None


def _product_url(url):
    absolute = urljoin(BASE, url or "").split("#")[0]
    parsed = urlparse(absolute)

    if parsed.netloc.lower() not in {"www.sabina.com", "sabina.com"}:
        return False

    parts = [p for p in parsed.path.split("/") if p]
    if not parts:
        return False

    if parts[0].lower() in {"it", "es", "en", "fr", "de", "pt", "nl", "pl"}:
        parts = parts[1:]

    if not parts:
        return False

    return parts[0].lower() not in IGNORED_PATHS


def _candidate_score(anchor, query):
    href = anchor.get("href", "")
    title = _clean(anchor.get("title"))
    aria = _clean(anchor.get("aria-label"))
    text = _clean(anchor.get_text(" ", strip=True))

    pieces = [title, aria, text, href]

    node = anchor
    for _ in range(6):
        node = getattr(node, "parent", None)
        if node is None:
            break
        block = _clean(node.get_text(" ", strip=True))
        if block:
            pieces.append(block[:2500])

        # Product cards normally contain a price.
        if PRICE_RE.search(block):
            break

    combined = " ".join(pieces)
    score = 0

    if _matches(combined, query):
        score += 100

    query_tokens = set(_tokens(query))
    combined_tokens = set(_tokens(combined))
    score += 10 * len(query_tokens & combined_tokens)

    if PRICE_RE.search(combined):
        score += 15

    if "/it/" in href.lower() or "/en/" in href.lower():
        score += 2

    return score


def _search_urls(query):
    q = quote_plus(query)
    return [
        BASE + "/it/ricerca?search_query=" + q,
        BASE + "/it/ricerca_old?s=" + q,
        BASE + "/it/ricerca?s=" + q,
        BASE + "/it/ricerca_old?search_query=" + q,
    ]


def _query_variants(query):
    original = _clean(query)
    if not original:
        return []

    variants = [original]
    normalized = _norm(original)

    if normalized and normalized not in variants:
        variants.append(normalized)

    tokens = _tokens(original)

    # Keep discovery generic: no product names are seeded.
    for token in tokens:
        if len(token) >= 3 and token not in variants:
            variants.append(token)

    return variants


def _discover_from_search(session, query):
    candidates = []
    seen = set()

    for search_url in _search_urls(query):
        try:
            response = session.get(
                search_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if not response.ok:
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        scored = []

        for anchor in soup.select("a[href]"):
            href = anchor.get("href", "")
            absolute = urljoin(BASE, href).split("#")[0]

            if not _product_url(absolute):
                continue

            path = urlparse(absolute).path.rstrip("/")
            if not path or path in seen:
                continue

            score = _candidate_score(anchor, query)
            if score <= 0:
                continue

            scored.append((score, absolute))

        scored.sort(key=lambda item: item[0], reverse=True)

        for score, absolute in scored[:40]:
            path = urlparse(absolute).path.rstrip("/")
            if path in seen:
                continue

            seen.add(path)
            candidates.append((score, absolute))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in candidates[:40]]


def _discover_from_sitemap(session, query):
    """
    Generic sitemap fallback. It follows sitemap indexes recursively and
    only keeps URLs whose slug contains at least one query token.
    No product is hard-coded.
    """
    roots = [
        BASE + "/sitemap_index_shop_1.xml",
        BASE + "/sitemap.xml",
        BASE + "/sitemap_index.xml",
        BASE + "/it/sitemap.xml",
        BASE + "/it/sitemap_index.xml",
    ]

    queue = list(roots)
    seen_sitemaps = set()
    product_urls = []

    q_tokens = set(_tokens(query))

    while queue and len(seen_sitemaps) < 12 and len(product_urls) < 100:
        sitemap_url = queue.pop(0)

        if sitemap_url in seen_sitemaps:
            continue
        seen_sitemaps.add(sitemap_url)

        try:
            response = session.get(
                sitemap_url,
                headers=HEADERS,
                timeout=TIMEOUT,
                allow_redirects=True,
            )
        except requests.RequestException:
            continue

        if not response.ok:
            continue

        text = response.text

        try:
            root = BeautifulSoup(text, "xml")
        except Exception:
            continue

        for loc in root.find_all("loc"):
            value = _clean(loc.get_text())
            if not value:
                continue

            if value.lower().endswith(".xml") or "sitemap" in value.lower():
                if value not in seen_sitemaps and len(seen_sitemaps) < 12:
                    queue.append(value)
                continue

            if not _product_url(value):
                continue

            slug = _norm(urlparse(value).path.replace("/", " "))
            if q_tokens and not any(token in slug for token in q_tokens):
                continue

            product_urls.append(value)

    # Deduplicate while preserving order.
    out = []
    seen = set()
    for url in product_urls:
        key = url.split("?")[0].rstrip("/")
        if key not in seen:
            seen.add(key)
            out.append(key)

    return out[:40]


def _availability(soup):
    text = _norm(soup.get_text(" ", strip=True))

    if any(
        word in text
        for word in (
            "out of stock",
            "sold out",
            "non disponibile",
            "esaurito",
            "rupture de stock",
            "indisponible",
            "ausverkauft",
        )
    ):
        return "out_of_stock"

    if any(
        word in text
        for word in (
            "in stock",
            "disponibile",
            "en stock",
            "auf lager",
        )
    ):
        return "in_stock"

    return "unknown"


def _product_from_html(session, url, query):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    final_url = response.url.split("#")[0]
    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    name = _clean(h1.get_text(" ", strip=True)) if h1 else ""

    if not name:
        meta = soup.select_one('meta[property="og:title"]')
        name = _clean(meta.get("content")) if meta else ""

    # Final validation is performed against the actual product name.
    if not name or not _matches(name, query):
        return None

    price = None

    # JSON-LD first, as done by the working store adapters.
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            obj = stack.pop(0)

            if isinstance(obj, list):
                stack.extend(obj)
                continue

            if not isinstance(obj, dict):
                continue

            offers = obj.get("offers")
            if isinstance(offers, dict):
                offers = [offers]
            elif not isinstance(offers, list):
                offers = []

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                price = _price(
                    offer.get("price")
                    if offer.get("price") is not None
                    else offer.get("lowPrice")
                )
                if price is not None:
                    break

            if price is not None:
                break

    if price is None:
        for selector in (
            '[itemprop="price"]',
            'meta[property="product:price:amount"]',
            'meta[itemprop="price"]',
        ):
            node = soup.select_one(selector)
            if node:
                price = _price(
                    node.get("content")
                    if node.name == "meta"
                    else node.get_text(" ", strip=True)
                )
                if price is not None:
                    break

    if price is None:
        price = _price(soup.get_text(" ", strip=True))

    if price is None:
        return None

    image = None
    meta_image = soup.select_one('meta[property="og:image"]')
    if meta_image:
        image = urljoin(final_url, meta_image.get("content", ""))

    size = _size_ml(name)
    concentration = _concentration(name)
    availability = _availability(soup)

    return {
        "store": STORE,
        "source": {
            "source_name": name,
            "source_brand": None,
            "url": final_url,
            "image": image,
        },
        "identity": {
            "gtin": None,
            "mpn": None,
            "sku": None,
            "store_product_id": None,
            "store_variant_id": None,
        },
        "attributes": {
            "size_ml": {
                "value": size,
                "source": "product_title",
            } if size is not None else None,
            "concentration": {
                "value": concentration,
                "source": "product_title",
            } if concentration else None,
            "gender": {
                "value": "unknown",
                "source": "not_explicit",
            },
            "packaging_type": {
                "value": "product",
                "source": "default",
            },
        },
        "offer": {
            "price": round(price, 2),
            "currency": "EUR",
            "availability": availability,
        },
        "provenance": {
            "source_page": final_url,
            "name_source": "h1_or_og_title",
            "price_source": "jsonld_or_page",
        },
        "raw_data": {},
        "name": name,
        "price": f"{price:.2f}".replace(".", ",") + " €",
        "url": final_url,
        "available": availability == "in_stock",
    }


def search(query):
    query = _clean(query)
    if not query:
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        candidates = []
        seen = set()

        # Same philosophy as the working Bplatz/Orioudh adapters:
        # discover candidate URLs first, then open/validate product pages.
        for variant in _query_variants(query):
            for url in _discover_from_search(session, variant):
                key = url.split("?")[0].rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(url)

        # Sitemap is only a fallback discovery mechanism.
        if not candidates:
            for url in _discover_from_sitemap(session, query):
                key = url.split("?")[0].rstrip("/")
                if key in seen:
                    continue
                seen.add(key)
                candidates.append(url)

        results = []
        result_keys = set()

        for url in candidates[:40]:
            item = _product_from_html(session, url, query)
            if not item:
                continue

            key = (
                item["name"].lower(),
                item["price"],
                item.get("attributes", {})
                    .get("size_ml", {})
                    .get("value")
                if isinstance(
                    item.get("attributes", {}).get("size_ml"),
                    dict,
                )
                else None,
            )

            if key in result_keys:
                continue

            result_keys.add(key)
            results.append(item)

            if len(results) >= 20:
                break

        return results

    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generic Sabina store adapter")
    parser.add_argument("query")
    args = parser.parse_args()

    print(json.dumps(search(args.query), ensure_ascii=False, indent=2))
