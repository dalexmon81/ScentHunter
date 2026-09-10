import asyncio
import json
import re
import time
from urllib.parse import unquote
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from scrapers.common.discovery import extract_json_ld_blocks, extract_json_ld_products


BASE_URL = "https://www.parfum-zentrum.de"
SEARCH_URL = BASE_URL + "/suchen/"
SEARCH_DEADLINE = 14.0
PRODUCT_TIMEOUT = 2.5

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


async def _extract_product_urls_with_playwright(query):
    """Extract product URLs using Playwright to handle JavaScript rendering."""
    query = str(query or "").strip()
    if not query:
        return []

    urls = []
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            page.set_default_timeout(8000)

            try:
                search_params = f"?search={query}&submit=Suche"
                await page.goto(SEARCH_URL + search_params, wait_until="networkidle")
                await page.wait_for_selector("a", timeout=5000)
                content = await page.content()
                soup = BeautifulSoup(content, "html.parser")

                for link in soup.find_all("a", href=True):
                    href = link.get("href", "").strip()
                    if not href:
                        continue

                    if href.startswith("/"):
                        href = BASE_URL + href
                    elif not href.startswith("http"):
                        href = BASE_URL + "/" + href

                    if re.search(r"_z\d+", href, re.I):
                        if href not in urls:
                            urls.append(href)

                if len(urls) > 0:
                    return urls[:40]

            finally:
                await browser.close()

    except Exception as e:
        print(f"PLAYWRIGHT ERROR: {type(e).__name__}: {e}")
        return []

    return urls


def _extract_product(url, query):
    """Extract product details from a product page URL."""
    try:
        import requests
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

    product_records = extract_json_ld_products(response.text)
    price = None
    for data in product_records:
        offers = data.get("offers", {})
        if isinstance(offers, dict):
            price = _parse_price(offers.get("price"))
        elif isinstance(offers, list):
            for offer in offers:
                price = _parse_price(offer.get("price") if isinstance(offer, dict) else None)
                if price:
                    break
        if price:
            break

    if price is None:
        for meta in soup.find_all("meta"):
            if meta.get("property") == "product:price:amount" or meta.get("itemprop") == "price":
                price = _parse_price(meta.get("content"))
                if price:
                    break

    if price is None:
        return None

    brand = None
    for data in extract_json_ld_blocks(response.text):
        raw_brand = data.get("brand")
        brand = raw_brand.get("name") if isinstance(raw_brand, dict) else raw_brand
        if brand:
            break

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
    """Main search function - synchronous wrapper for async Playwright."""
    query = str(query or "").strip()
    if not query:
        return []

    started = time.monotonic()

    try:
        product_urls = asyncio.run(_extract_product_urls_with_playwright(query))
    except Exception as e:
        print(f"PLAYWRIGHT EXTRACTION ERROR: {type(e).__name__}: {e}")
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
