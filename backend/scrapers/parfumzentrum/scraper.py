from collections import deque
import json
import re
import time
from urllib.parse import parse_qsl, unquote, urlencode, urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.parfum-zentrum.de"
SEARCH_URL = BASE_URL + "/suchen/"
SEARCH_DEADLINE = 14.0
SEARCH_TIMEOUT = 5.0
PRODUCT_TIMEOUT = 2.5
MAX_PRODUCT_URLS = 40
MAX_RESULT_PAGES = 8

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

PRODUCT_RE = re.compile(r"_z\d+\b", re.I)
PAGE_RE = re.compile(r"(?:^|[?#&])Seite=(\d+)\b", re.I)

STOPWORDS = {
    "eau", "de", "the", "for", "and", "spray", "ml", "man", "woman",
    "men", "women", "herren", "damen",
}


def _tokens(text):
    return [
        x.lower()
        for x in re.findall(r"[A-Za-zÀ-ÿ0-9]+", unquote(str(text or "")))
        if len(x) > 1
    ]


def _concentration(text):
    value = unquote(str(text or ""))
    if re.search(r"\beau\s+de\s+toilette\b|\bedt\b", value, re.I):
        return "edt"
    if re.search(r"\beau\s+de\s+parfum\b|\bedp\b", value, re.I):
        return "edp"
    if re.search(r"\bextrait(?:\s+de\s+parfum)?\b", value, re.I):
        return "extrait"
    return ""


def _matches_query(name, query):
    name_tokens = set(_tokens(name))
    wanted = {x for x in _tokens(query) if x not in STOPWORDS}

    if not wanted or not wanted.issubset(name_tokens):
        return False

    requested_concentration = _concentration(query)
    return (
        not requested_concentration
        or _concentration(name) == requested_concentration
    )


def _parse_price(value):
    if value is None:
        return None

    raw = str(value).strip().replace("\xa0", " ")
    raw = raw.replace("€", "").strip()

    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        number = float(raw)
        return number if 0 < number < 10000 else None

    match = re.search(r"\d{1,5}(?:[.,]\d{2})", raw)
    if not match:
        return None

    number = match.group(0)

    if "," in number:
        if "." in number:
            number = number.replace(".", "").replace(",", ".")
        else:
            number = number.replace(",", ".")
    elif number.count(".") > 1:
        number = number.replace(".", "")

    try:
        result = float(number)
    except ValueError:
        return None

    return result if 0 < result < 10000 else None


def _search_url(query, page=None):
    params = {"search": str(query or "").strip(), "submit": "Suche"}
    if page and int(page) > 1:
        params["Seite"] = str(int(page))
    return SEARCH_URL + "?" + urlencode(params)


def _get(session, url, timeout):
    try:
        response = session.get(url, timeout=timeout)
    except requests.RequestException:
        return None
    return response if response.status_code == 200 else None


def _allowed_host(host):
    host = str(host or "").lower()
    return not host or host in {"parfum-zentrum.de", "www.parfum-zentrum.de"}


def _first_query_value(pairs, key):
    for name, value in pairs:
        if name == key:
            return value
    return None


def _upsert_query_value(pairs, key, value):
    updated = []
    replaced = False
    for name, current in pairs:
        if name == key:
            if not replaced:
                updated.append((name, str(value)))
                replaced = True
            continue
        updated.append((name, current))
    if not replaced:
        updated.append((key, str(value)))
    return updated


def _normalize_product_url(href):
    parts = urlsplit(urljoin(BASE_URL + "/", str(href or "").strip()))
    if not _allowed_host(parts.hostname):
        return ""
    path = (parts.path or "/").rstrip("/") or "/"
    return urlunsplit((parts.scheme or "https", parts.netloc or urlsplit(BASE_URL).netloc, path, "", ""))


def _page_request_url(href, current_url):
    absolute = urljoin(current_url, str(href or "").strip())
    parts = urlsplit(absolute)
    if not _allowed_host(parts.hostname):
        return ""
    query = parse_qsl(parts.query, keep_blank_values=True)
    fragment = parse_qsl(parts.fragment, keep_blank_values=True)
    current_query = parse_qsl(urlsplit(current_url).query, keep_blank_values=True)

    page_number = _first_query_value(query, "Seite") or _first_query_value(fragment, "Seite")
    if not page_number:
        return ""
    query = _upsert_query_value(query, "Seite", page_number)

    search_value = _first_query_value(query, "search") or _first_query_value(current_query, "search")
    if search_value:
        query = _upsert_query_value(query, "search", search_value)

    submit_value = _first_query_value(query, "submit") or _first_query_value(current_query, "submit") or "Suche"
    query = _upsert_query_value(query, "submit", submit_value)

    search_parts = urlsplit(SEARCH_URL)
    return urlunsplit((
        search_parts.scheme or "https",
        search_parts.netloc or urlsplit(BASE_URL).netloc,
        search_parts.path or "/suchen/",
        urlencode(query),
        "",
    ))


def _page_number(url):
    query = dict(parse_qsl(urlsplit(str(url or "")).query, keep_blank_values=True))
    try:
        return int(query.get("Seite", "1"))
    except (TypeError, ValueError):
        return 9999


def _extract_product_urls_from_html(html):
    soup = BeautifulSoup(html or "", "html.parser")
    urls = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not PRODUCT_RE.search(href):
            continue
        normalized = _normalize_product_url(href)
        if normalized and normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)

    return urls


def _extract_page_urls_from_html(html, current_url):
    soup = BeautifulSoup(html or "", "html.parser")
    pages = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not PAGE_RE.search(href):
            continue
        page_url = _page_request_url(href, current_url)
        if page_url and page_url not in seen:
            seen.add(page_url)
            pages.append(page_url)

    pages.sort(key=_page_number)
    return pages


def _extract_product_urls(session, query, deadline):
    query = str(query or "").strip()
    if not query:
        return []

    pending_pages = deque([_search_url(query)])
    seen_pages = set()
    product_urls = []
    seen_products = set()

    while pending_pages and len(seen_pages) < MAX_RESULT_PAGES and time.monotonic() < deadline:
        page_url = pending_pages.popleft()
        if page_url in seen_pages:
            continue
        seen_pages.add(page_url)

        response = _get(session, page_url, timeout=SEARCH_TIMEOUT)
        if not response:
            continue

        for product_url in _extract_product_urls_from_html(response.text):
            if product_url not in seen_products:
                seen_products.add(product_url)
                product_urls.append(product_url)
                if len(product_urls) >= MAX_PRODUCT_URLS:
                    return product_urls[:MAX_PRODUCT_URLS]

        for extra_page in _extract_page_urls_from_html(response.text, response.url):
            if extra_page not in seen_pages and extra_page not in pending_pages:
                pending_pages.append(extra_page)

    return product_urls[:MAX_PRODUCT_URLS]


def _extract_product(session, url, query, timeout):
    """Extract product details from a product page URL."""
    response = _get(session, url, timeout=timeout)
    if not response:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    if not _matches_query(name, query):
        return None

    size_match = re.search(
        r"(?<!\d)(\d{1,4}(?:[.,]\d+)?)\s*ml\b",
        name,
        re.I,
    )
    size_ml = None
    if size_match:
        try:
            size_ml = float(size_match.group(1).replace(",", "."))
        except ValueError:
            pass

    concentration = ""
    if re.search(r"\beau\s+de\s+toilette\b|\bedt\b", name, re.I):
        concentration = "Eau de Toilette"
    elif re.search(r"\beau\s+de\s+parfum\b|\bedp\b", name, re.I):
        concentration = "Eau de Parfum"
    elif re.search(r"\bextrait(?:\s+de\s+parfum)?\b", name, re.I):
        concentration = "Extrait de Parfum"

    page_text = soup.get_text(" ", strip=True).lower()
    if any(x in page_text for x in (
        "nicht lieferbar", "nicht vorrätig", "ausverkauft",
    )):
        return None

    price = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            offers = data.get("offers", {})
            if isinstance(offers, dict):
                price = _parse_price(offers.get("price"))
            elif isinstance(offers, list):
                for offer in offers:
                    price = _parse_price(offer.get("price"))
                    if price:
                        break
            if price:
                break
        except:
            pass

    if price is None:
        for meta in soup.find_all("meta"):
            if meta.get("property") == "product:price:amount" or meta.get("itemprop") == "price":
                price = _parse_price(meta.get("content"))
                if price:
                    break

    if price is None:
        return None

    brand = None
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            brand = data.get("brand", {}).get("name") if isinstance(data.get("brand"), dict) else data.get("brand")
            if brand:
                break
        except:
            pass

    availability = "in_stock"
    if any(x in page_text for x in ("nicht lieferbar", "nicht vorrätig", "ausverkauft")):
        availability = "out_of_stock"

    return {
        "store": "ParfumZentrum",
        "shop": "parfumzentrum",
        "source": {
            "source_name": name,
            "source_brand": brand,
            "url": url,
            "image": None,
        },
        "name": name,
        "price": f"{price:.2f}€",
        "url": url,
        "available": availability == "in_stock",
        "size_ml": size_ml,
        "concentration": concentration,
        "price_value": price,
        "availability": availability,
    }


def search(query):
    """Main search function using HTML parsing only."""
    query = str(query or "").strip()
    if not query:
        return []

    started = time.monotonic()
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        product_urls = _extract_product_urls(
            session,
            query,
            started + SEARCH_DEADLINE,
        )
    except Exception as e:
        print(f"SEARCH EXTRACTION ERROR: {type(e).__name__}: {e}")
        return []

    if not product_urls:
        return []

    results = []
    seen = set()

    for url in product_urls[:24]:
        remaining = SEARCH_DEADLINE - (time.monotonic() - started)
        if remaining <= 0:
            break

        try:
            item = _extract_product(
                session,
                url,
                query,
                timeout=min(PRODUCT_TIMEOUT, remaining),
            )
        except Exception as e:
            print(f"PRODUCT EXTRACTION ERROR: {type(e).__name__}: {e}")
            item = None

        if not item:
            continue

        key = (item["name"].lower(), item["price"], item.get("size_ml"))
        if key in seen:
            continue

        seen.add(key)
        results.append(item)

    results.sort(key=lambda x: (
        0 if x.get("available") else 1,
        float(x.get("price_value") or 999999),
    ))

    return results
