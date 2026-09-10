import json
import re
import time
from urllib.parse import unquote, urljoin, urlparse, urlunparse
import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.parfum-zentrum.de"
SEARCH_URL = BASE_URL + "/suchen/"
SEARCH_DEADLINE = 14.0
PRODUCT_TIMEOUT = 2.5

STOPWORDS = {
    "eau", "de", "the", "for", "and", "spray", "ml", "man", "woman",
    "men", "women", "herren", "damen",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9",
}

PRODUCT_RE = re.compile(r"_z[0-9a-z-]*", re.I)
PRODUCT_HINT_RE = re.compile(
    r"(?:(?<!\d)\d{2,4}\s*ml\b|\b(?:eau|parfum|edt|edp|extrait)\b)",
    re.I,
)
NON_PRODUCT_PATH_RE = re.compile(
    r"/(?:suchen|marken|kategorien|warenkorb|konto|kontakt|impressum|datenschutz)(?:/|$)",
    re.I,
)


def _normalize_product_url(href):
    href = str(href or "").strip()
    if not href:
        return None

    parsed = urlparse(urljoin(BASE_URL, href))
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if host != "parfum-zentrum.de":
        return None
    if parsed.scheme not in {"http", "https"}:
        return None

    path = (parsed.path or "").strip()
    if not path or path == "/":
        return None

    normalized = urlunparse(("https", "www.parfum-zentrum.de", path.rstrip("/"), "", "", ""))
    return normalized


def _extract_product_urls_from_html(html):
    soup = BeautifulSoup(html or "", "html.parser")
    urls = []
    seen = set()

    for link in soup.find_all("a", href=True):
        normalized = _normalize_product_url(link.get("href"))
        if not normalized:
            continue

        path = urlparse(normalized).path or ""
        if NON_PRODUCT_PATH_RE.search(path):
            continue

        # Keep compatibility with historical product URLs while allowing
        # server-rendered variants that no longer expose a strict `_z123` suffix.
        if not PRODUCT_RE.search(path) and not PRODUCT_HINT_RE.search(path.replace("-", " ")):
            continue

        if normalized not in seen:
            seen.add(normalized)
            urls.append(normalized)

    return urls


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
    """Check if product name matches the search query."""
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


def _extract_product_urls(query):
    """Extract product URLs using requests + BeautifulSoup."""
    query = str(query or "").strip()
    if not query:
        return []

    urls = []
    seen = set()
    
    try:
        session = requests.Session()
        session.headers.update(HEADERS)
        
        # Try first page
        search_params = f"?search={query}&submit=Suche"
        response = session.get(SEARCH_URL + search_params, timeout=5)
        
        if response.status_code != 200:
            return []
        
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Extract product links from first page.
        for href in _extract_product_urls_from_html(response.text):
            if href not in seen:
                seen.add(href)
                urls.append(href)
        
        # Try to find and follow pagination links (pages 2, 3, etc)
        page_num = 2
        while len(urls) < 40 and page_num <= 5:
            try:
                # ParfumZentrum uses #Seite=2 anchor, but we need to make actual requests
                # Try different pagination patterns
                pagination_url = SEARCH_URL + f"?search={query}&submit=Suche&page={page_num}"
                response = session.get(pagination_url, timeout=5)
                
                if response.status_code != 200:
                    break
                
                soup = BeautifulSoup(response.text, "html.parser")
                found_on_page = 0
                
                for href in _extract_product_urls_from_html(response.text):
                    if href not in seen:
                        seen.add(href)
                        urls.append(href)
                        found_on_page += 1
                
                if found_on_page == 0:
                    break
                
                page_num += 1
            except Exception:
                break
        
        session.close()
        
    except Exception as e:
        print(f"ERROR extracting URLs: {type(e).__name__}: {e}")
        return []

    return urls[:40]


def _extract_product(url, query):
    """Extract product details from a product page URL."""
    try:
        response = requests.get(url, timeout=PRODUCT_TIMEOUT, headers=HEADERS)
    except Exception:
        return None

    if response.status_code != 200:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    h1 = soup.find("h1")
    if not h1:
        return None

    name = " ".join(h1.stripped_strings)

    # CRITICAL FIX: Filter by query BEFORE processing
    if not _matches_query(name, query):
        return None

    # Check availability BEFORE wasting time on price extraction
    page_text = soup.get_text(" ", strip=True).lower()
    if any(x in page_text for x in (
        "nicht lieferbar", "nicht vorrätig", "ausverkauft",
    )):
        return None

    # Extract price (required field)
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

    # If no price found, skip this product
    if price is None:
        return None

    # Extract optional fields
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
    """Main search function - extract products using requests."""
    query = str(query or "").strip()
    if not query:
        return []

    started = time.monotonic()

    try:
        product_urls = _extract_product_urls(query)
    except Exception as e:
        print(f"URL EXTRACTION ERROR: {type(e).__name__}: {e}")
        return []

    if not product_urls:
        return []

    results = []
    seen = set()

    # Process ALL URLs (not just first 24) to maximize chances of finding matches
    for url in product_urls:
        remaining = max(1.0, 12.0 - (time.monotonic() - started))
        if remaining <= 0:
            break

        try:
            item = _extract_product(url, query)
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
