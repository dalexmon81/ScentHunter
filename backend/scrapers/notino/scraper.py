"""
Notino diagnostic V8.

Key finding from V7:
- direct product navigation in a fresh browser context returns 200;
- product navigation after visiting search in the same context returns 403;
- the click test is deliberately removed because it can leave a browser navigation
  pending and is not needed anymore.

V8 therefore tests the clean path:
search discovery -> close search context -> fresh browser context -> product pages.

It also prints only compact diagnostics and returns a small JSON report.
No product-specific rules, URLs, seeds or names are embedded.
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
MAX_CANDIDATES = 5

SCRAPER_VERSION = "notino-DIAGNOSTIC-2026-08-18-v8"

P_ID_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)
PRICE_RE = re.compile(r"\d+(?:[,.]\d{1,2})?\s*€", re.I)
SIZE_RE = re.compile(r"\b\d+(?:[,.]\d+)?\s*(?:ml|g|kg|l|pcs?)\b", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def abs_url(page_url, href):
    return urljoin(page_url, href).split("#", 1)[0]


def internal(url):
    host = urlparse(url).netloc.lower()
    return host == "notino.fr" or host.endswith(".notino.fr")


def jsonld_objects(soup):
    objects = []

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

        def walk(value):
            if isinstance(value, dict):
                objects.append(value)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(data)

    return objects


def product_objects(objects):
    result = []

    for obj in objects:
        kind = obj.get("@type")
        kinds = kind if isinstance(kind, list) else [kind]

        if any(str(k).lower() == "product" for k in kinds):
            result.append(obj)

    return result


def extract_product_data(page):
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title = clean(page.title())
    h1 = clean(
        page.locator("h1").first.inner_text(timeout=3000)
    ) if page.locator("h1").count() else ""

    canonical = ""
    node = soup.find("link", rel="canonical")
    if node:
        canonical = abs_url(page.url, node.get("href"))

    products = product_objects(jsonld_objects(soup))
    data = []

    for product in products:
        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        elif isinstance(brand, list):
            brand = ", ".join(
                clean(x.get("name") if isinstance(x, dict) else x)
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

        offer_data = []
        for offer in offers[:5]:
            if isinstance(offer, dict):
                offer_data.append({
                    "price": offer.get("price"),
                    "currency": offer.get("priceCurrency"),
                    "availability": offer.get("availability"),
                    "url": offer.get("url"),
                })

        data.append({
            "name": clean(product.get("name")),
            "brand": clean(brand),
            "sku": clean(product.get("sku")),
            "mpn": clean(product.get("mpn")),
            "product_id": clean(product.get("productID")),
            "image": clean(image),
            "offers": offer_data,
        })

    text = clean(soup.get_text(" ", strip=True))

    return {
        "title": title,
        "h1": h1,
        "canonical": canonical,
        "jsonld_products": data,
        "price_examples": PRICE_RE.findall(text)[:10],
        "size_examples": SIZE_RE.findall(text)[:10],
        "bytes": len(html.encode("utf-8", errors="ignore")),
    }


def discover_candidates(page):
    soup = BeautifulSoup(page.content(), "html.parser")
    candidates = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = abs_url(page.url, anchor["href"])

        if not url or not internal(url):
            continue

        path = urlparse(url).path.rstrip("/") + "/"
        match = P_ID_RE.search(path)

        if not match:
            continue

        key = url.lower()
        if key in seen:
            continue
        seen.add(key)

        text = clean(anchor.get_text(" ", strip=True))
        img = anchor.find("img")
        alt = clean(img.get("alt")) if img else ""

        candidates.append({
            "url": url,
            "p_id": match.group(1),
            "text": text[:300],
            "alt": alt[:300],
        })

        if len(candidates) >= MAX_CANDIDATES:
            break

    return candidates


def browser_context(pw):
    return pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )


def context_options():
    return {
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "locale": "fr-FR",
        "viewport": {"width": 1365, "height": 900},
    }


def search_page(browser, url):
    context = browser.new_context(**context_options())
    page = context.new_page()

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=TIMEOUT,
        )
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(800)

        status = response.status if response else None
        candidates = discover_candidates(page) if status == 200 else []

        print(
            f"NOTINO_V8_SEARCH: status={status} "
            f"url={page.url} candidates={len(candidates)}",
            flush=True,
        )

        return candidates

    finally:
        page.close()
        context.close()


def open_products(browser, candidates):
    results = []

    # IMPORTANT: this is a NEW context, not the search context.
    context = browser.new_context(**context_options())

    try:
        for index, candidate in enumerate(candidates, 1):
            page = context.new_page()

            try:
                response = page.goto(
                    candidate["url"],
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT,
                )

                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=10000,
                    )
                except Exception:
                    pass

                page.wait_for_timeout(700)

                status = response.status if response else None

                if status == 200:
                    extracted = extract_product_data(page)
                else:
                    extracted = {
                        "title": clean(page.title()),
                        "h1": "",
                        "canonical": "",
                        "jsonld_products": [],
                        "price_examples": [],
                        "size_examples": [],
                        "bytes": len(
                            page.content().encode(
                                "utf-8",
                                errors="ignore",
                            )
                        ),
                    }

                result = {
                    "index": index,
                    "candidate": candidate,
                    "status": status,
                    "url": page.url,
                    "data": extracted,
                }

                results.append(result)

                print(
                    f"NOTINO_V8_PRODUCT[{index}]: "
                    f"status={status} "
                    f"p_id={candidate['p_id']} "
                    f"title={extracted['title']!r} "
                    f"jsonld_products="
                    f"{len(extracted['jsonld_products'])}",
                    flush=True,
                )

                for product in extracted["jsonld_products"][:2]:
                    print(
                        f"NOTINO_V8_DATA[{index}]: "
                        f"name={product['name']!r} "
                        f"brand={product['brand']!r} "
                        f"sku={product['sku']!r} "
                        f"product_id={product['product_id']!r} "
                        f"offers={product['offers']!r} "
                        f"image={'yes' if product['image'] else 'no'}",
                        flush=True,
                    )

            except Exception as exc:
                print(
                    f"NOTINO_V8_PRODUCT_ERROR[{index}]: "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

                results.append({
                    "index": index,
                    "candidate": candidate,
                    "status": None,
                    "error": f"{type(exc).__name__}: {exc}",
                })

            finally:
                page.close()

    finally:
        context.close()

    return results


def search(query):
    query = clean(query)

    print(
        f"NOTINO_V8_VERSION: {SCRAPER_VERSION}",
        flush=True,
    )
    print(
        f"NOTINO_V8_START: query={query!r}",
        flush=True,
    )

    if not query:
        return []

    search_url = (
        SEARCH_URL
        + "?exps="
        + quote(query)
    )

    with sync_playwright() as pw:
        browser = browser_context(pw)

        try:
            # Phase 1: discovery.
            candidates = search_page(
                browser,
                search_url,
            )

            for i, candidate in enumerate(candidates, 1):
                print(
                    f"NOTINO_V8_CANDIDATE[{i}]: "
                    f"p_id={candidate['p_id']} "
                    f"url={candidate['url']} "
                    f"text={candidate['text']!r}",
                    flush=True,
                )

            # Phase 2: fresh context product opening.
            results = open_products(
                browser,
                candidates,
            )

            ok = [
                x for x in results
                if x.get("status") == 200
            ]

            product_count = sum(
                len(
                    x.get("data", {}).get(
                        "jsonld_products",
                        [],
                    )
                )
                for x in ok
            )

            print(
                f"NOTINO_V8_END: "
                f"candidates={len(candidates)} "
                f"opened={len(results)} "
                f"ok={len(ok)} "
                f"jsonld_products={product_count}",
                flush=True,
            )

            # Keep the returned JSON intentionally small.
            summary = []
            for item in results:
                data = item.get("data", {})
                products = data.get("jsonld_products", [])

                summary.append({
                    "p_id": item["candidate"]["p_id"],
                    "url": item["url"],
                    "status": item.get("status"),
                    "title": data.get("title"),
                    "products": products[:2],
                })

            return [{
                "diagnostic": True,
                "version": SCRAPER_VERSION,
                "query": query,
                "search_status": 200 if candidates else None,
                "candidates": len(candidates),
                "products": summary,
            }]

        finally:
            browser.close()


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
