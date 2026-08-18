"""
Notino diagnostic V9.

Purpose:
- Stop after the FIRST discovered product candidate.
- Use one completely fresh Chromium browser process for the search.
- Close it.
- Use a SECOND completely fresh Chromium browser process for the product page.
- Extract the real Product JSON-LD and print a compact result.
- Return only a tiny JSON object, so /test-store cannot become a huge/infinite
  diagnostic response.

No product-specific names, URLs, seeds or exceptions are embedded.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
TIMEOUT = 30000

SCRAPER_VERSION = "notino-DIAGNOSTIC-2026-08-18-v9"

P_ID_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def absolute(page_url, href):
    return urljoin(page_url, href).split("#", 1)[0]


def internal(url):
    host = urlparse(url).netloc.lower()
    return host == "notino.fr" or host.endswith(".notino.fr")


def options():
    return {
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "locale": "fr-FR",
        "viewport": {"width": 1365, "height": 900},
    }


def launch(pw):
    return pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )


def find_first_product(page):
    soup = BeautifulSoup(page.content(), "html.parser")

    for anchor in soup.find_all("a", href=True):
        url = absolute(page.url, anchor["href"])

        if not url or not internal(url):
            continue

        path = urlparse(url).path.rstrip("/") + "/"
        match = P_ID_RE.search(path)

        if not match:
            continue

        text = clean(anchor.get_text(" ", strip=True))
        image = anchor.find("img")
        alt = clean(image.get("alt")) if image else ""

        return {
            "url": url,
            "p_id": match.group(1),
            "text": text[:300],
            "alt": alt[:300],
        }

    return None


def extract_product(page):
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title = clean(page.title())

    h1 = ""
    node = soup.find("h1")
    if node:
        h1 = clean(node.get_text(" ", strip=True))

    canonical = ""
    node = soup.find("link", rel="canonical")
    if node:
        canonical = absolute(page.url, node.get("href"))

    product = None

    for script in soup.find_all(
        "script",
        attrs={"type": re.compile(r"application/ld\+json", re.I)},
    ):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        values = data if isinstance(data, list) else [data]

        stack = list(values)

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            kind = item.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]

            if any(
                str(k).lower() == "product"
                for k in kinds
            ):
                product = item
                break

            for value in item.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)

        if product:
            break

    if product:
        brand = product.get("brand")

        if isinstance(brand, dict):
            brand = brand.get("name")
        elif isinstance(brand, list):
            brand = ", ".join(
                clean(
                    x.get("name")
                    if isinstance(x, dict)
                    else x
                )
                for x in brand
            )

        image = product.get("image")

        if isinstance(image, list):
            image = image[0] if image else ""

        offers = product.get("offers")

        if isinstance(offers, dict):
            offers = [offers]
        elif not isinstance(offers, list):
            offers = []

        offer = offers[0] if offers else {}

        product = {
            "name": clean(product.get("name")),
            "brand": clean(brand),
            "sku": clean(product.get("sku")),
            "mpn": clean(product.get("mpn")),
            "product_id": clean(product.get("productID")),
            "image": clean(image),
            "price": offer.get("price"),
            "currency": offer.get("priceCurrency"),
            "availability": offer.get("availability"),
            "offer_url": absolute(
                page.url,
                offer.get("url"),
            ),
        }

    return {
        "title": title,
        "h1": h1,
        "canonical": canonical,
        "product": product,
        "bytes": len(
            html.encode("utf-8", errors="ignore")
        ),
    }


def search(query):
    query = clean(query)

    print(
        f"NOTINO_V9_VERSION: {SCRAPER_VERSION}",
        flush=True,
    )
    print(
        f"NOTINO_V9_START: query={query!r}",
        flush=True,
    )

    if not query:
        return []

    search_url = (
        SEARCH_URL
        + "?exps="
        + quote(query)
    )

    # ---------------------------------------------------------
    # PROCESS 1: discovery only.
    # ---------------------------------------------------------
    with sync_playwright() as pw:
        browser = launch(pw)

        try:
            context = browser.new_context(**options())
            page = context.new_page()

            try:
                response = page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT,
                )

                status = response.status if response else None

                print(
                    f"NOTINO_V9_SEARCH: "
                    f"status={status} url={page.url}",
                    flush=True,
                )

                if status != 200:
                    return [{
                        "diagnostic": True,
                        "version": SCRAPER_VERSION,
                        "query": query,
                        "stage": "search",
                        "status": status,
                    }]

                candidate = find_first_product(page)

            finally:
                page.close()
                context.close()

        finally:
            browser.close()

    if not candidate:
        print(
            "NOTINO_V9_END: no_product_candidate",
            flush=True,
        )

        return [{
            "diagnostic": True,
            "version": SCRAPER_VERSION,
            "query": query,
            "stage": "discovery",
            "candidate": None,
        }]

    print(
        f"NOTINO_V9_CANDIDATE: "
        f"p_id={candidate['p_id']} "
        f"url={candidate['url']} "
        f"text={candidate['text']!r}",
        flush=True,
    )

    # ---------------------------------------------------------
    # PROCESS 2: product only, in a NEW Chromium process.
    # ---------------------------------------------------------
    with sync_playwright() as pw:
        browser = launch(pw)

        try:
            context = browser.new_context(**options())
            page = context.new_page()

            try:
                response = page.goto(
                    candidate["url"],
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT,
                )

                status = response.status if response else None

                print(
                    f"NOTINO_V9_PRODUCT: "
                    f"status={status} "
                    f"url={page.url}",
                    flush=True,
                )

                if status == 200:
                    data = extract_product(page)

                    product = data.get("product")

                    if product:
                        print(
                            f"NOTINO_V9_DATA: "
                            f"name={product['name']!r} "
                            f"brand={product['brand']!r} "
                            f"sku={product['sku']!r} "
                            f"price={product['price']!r} "
                            f"currency={product['currency']!r} "
                            f"availability={product['availability']!r} "
                            f"image={'yes' if product['image'] else 'no'}",
                            flush=True,
                        )

                    result = {
                        "diagnostic": True,
                        "version": SCRAPER_VERSION,
                        "query": query,
                        "candidate": candidate,
                        "search_status": 200,
                        "product_status": status,
                        "product_page": data,
                    }

                else:
                    result = {
                        "diagnostic": True,
                        "version": SCRAPER_VERSION,
                        "query": query,
                        "candidate": candidate,
                        "search_status": 200,
                        "product_status": status,
                        "product_page": {
                            "title": clean(page.title()),
                            "url": page.url,
                        },
                    }

            finally:
                page.close()
                context.close()

        finally:
            browser.close()

    print(
        f"NOTINO_V9_END: "
        f"search=200 product={result['product_status']}",
        flush=True,
    )

    # Return exactly one compact result.
    return [result]


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
