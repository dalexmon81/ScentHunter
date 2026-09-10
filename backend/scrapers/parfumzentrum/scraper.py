import json
import re
import time
from urllib.parse import quote_plus, unquote, urljoin

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.parfum-zentrum.de"
SEARCH_URL = BASE_URL + "/suchen/"
SEARCH_DEADLINE = 14.0
PRODUCT_TIMEOUT = 2.5
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
}

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


def _normalize_url(value, base_url=BASE_URL + "/"):
    raw = str(value or "").strip()
    if not raw:
        return ""

    absolute = urljoin(base_url, raw)
    page_match = re.search(r"(?:[#?&])Seite=(\d+)", absolute, re.I)
    absolute = absolute.split("#", 1)[0]

    if page_match and not re.search(r"[?&]Seite=\d+", absolute, re.I):
        sep = "&" if "?" in absolute else "?"
        absolute = f"{absolute}{sep}Seite={page_match.group(1)}"

    return absolute


def _extract_product_urls(query):
    """Extract product URLs from search pages using plain HTML parsing."""
    query = str(query or "").strip()
    if not query:
        return []

    urls = []
    seen_urls = set()
    seen_pages = set()
    search_url = f"{SEARCH_URL}?search={quote_plus(query)}&submit=Suche"
    queue = [search_url]
    deadline = time.monotonic() + SEARCH_DEADLINE

    try:
        session = requests.Session()
        while queue and time.monotonic() < deadline and len(urls) < 40:
            page_url = queue.pop(0)
            if page_url in seen_pages:
                continue
            seen_pages.add(page_url)

            try:
                response = session.get(page_url, timeout=PRODUCT_TIMEOUT, headers=HEADERS)
            except requests.RequestException:
                continue

            if response.status_code != 200:
                continue

            soup = BeautifulSoup(response.text, "html.parser")

            for link in soup.find_all("a", href=True):
                product_url = _normalize_url(link.get("href", ""), page_url)
                if not product_url or not re.search(r"_z\d+", product_url, re.I):
                    continue
                if product_url in seen_urls:
                    continue
                seen_urls.add(product_url)
                urls.append(product_url)
                if len(urls) >= 40:
                    break

            for link in soup.find_all("a", href=True):
                href = str(link.get("href", "") or "").strip()
                next_page_url = _normalize_url(href, page_url)
                if not next_page_url:
                    continue
                if next_page_url in seen_pages or next_page_url in queue:
                    continue
                if "/suchen/" not in next_page_url or "search=" not in next_page_url:
                    continue
                label = " ".join(link.stripped_strings).strip()
                if (
                    re.search(r"(?:[#?&])Seite=\d+", href, re.I)
                    or re.search(r"[?&]Seite=\d+", next_page_url, re.I)
                    or label.isdigit()
                ):
                    queue.append(next_page_url)

        return urls[:40]
    except Exception as e:
        print(f"PARFUMZENTRUM URL EXTRACTION ERROR: {type(e).__name__}: {e}")
        return []


def _extract_product(url, query):
    """Extract product details from a product page URL."""
    try:
        response = requests.get(url, timeout=PRODUCT_TIMEOUT, headers={
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)"
        })
    except Exception:
        return None

    if response.status_code != 200:
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
    """Main search function using direct HTTP HTML parsing."""
    query = str(query or "").strip()
    if not query:
        return []

    started = time.monotonic()

    try:
        product_urls = _extract_product_urls(query)
    except Exception as e:
        print(f"PARFUMZENTRUM SEARCH EXTRACTION ERROR: {type(e).__name__}: {e}")
        return []

    if not product_urls:
        return []

    results = []
    seen = set()

    for url in product_urls[:24]:
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
