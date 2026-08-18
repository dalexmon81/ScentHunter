"""
Notino diagnostic V6 for ScentHunter.

Diagnostic only. Discovery is generic:
1. Open the search URL directly in Chromium.
2. Collect candidate links from the real search-result HTML.
3. Open candidate product pages directly, one by one.
4. Inspect product-page data: title, H1, canonical, JSON-LD Product,
   brand, name, offers/price, availability, images and product IDs.
5. No product names, URLs, seeds or special cases are embedded.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright


BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
TIMEOUT = 30000
MAX_CANDIDATES = 12

SCRAPER_VERSION = "notino-DIAGNOSTIC-2026-08-18-v6"

P_ID_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)
PRICE_RE = re.compile(r"\d+(?:[,.]\d{1,2})?\s*€", re.I)
SIZE_RE = re.compile(r"\b\d+(?:[,.]\d+)?\s*(?:ml|g|kg|l|pcs?)\b", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def absolute_url(page_url, href):
    if not href:
        return ""
    return urljoin(page_url, href).split("#", 1)[0]


def is_internal(url):
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return False
    return host == "notino.fr" or host.endswith(".notino.fr")


def extract_jsonld(soup):
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

        values = data if isinstance(data, list) else [data]

        def walk(value):
            if isinstance(value, dict):
                objects.append(value)
                for child in value.values():
                    if isinstance(child, (dict, list)):
                        walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(values)

    return objects


def product_jsonld(objects):
    products = []

    for obj in objects:
        kind = obj.get("@type")

        kinds = kind if isinstance(kind, list) else [kind]

        if any(
            str(item).lower() == "product"
            for item in kinds
        ):
            products.append(obj)

    return products


def candidate_links(page, query):
    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    candidates = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = absolute_url(page.url, anchor.get("href"))

        if not url or not is_internal(url):
            continue

        parsed = urlparse(url)
        path = parsed.path.rstrip("/") + "/"

        if (
            path == "/"
            or path.startswith("/search")
            or path.startswith("/cart")
            or path.startswith("/wishlist")
            or path.startswith("/mynotino")
        ):
            continue

        text = clean(anchor.get_text(" ", strip=True))
        img = anchor.find("img")
        alt = clean(img.get("alt")) if img else ""
        aria = clean(anchor.get("aria-label"))
        title_attr = clean(anchor.get("title"))

        visible = clean(
            " ".join([text, alt, aria, title_attr])
        )

        # Generic product signal:
        # - explicit product ID in URL, OR
        # - result-card text contains price/size and an image alt/text.
        has_pid = bool(P_ID_RE.search(path))
        has_price = bool(PRICE_RE.search(visible))
        has_size = bool(SIZE_RE.search(visible))
        has_product_text = len(visible) >= 12

        if not has_pid and not (
            has_price and has_product_text
        ):
            continue

        # Skip obvious non-product taxonomy/filter links.
        if (
            not has_pid
            and not has_size
            and not has_price
        ):
            continue

        key = url.lower()

        if key in seen:
            continue

        seen.add(key)

        candidates.append({
            "url": url,
            "p_id": (
                P_ID_RE.search(path).group(1)
                if P_ID_RE.search(path)
                else None
            ),
            "text": text[:500],
            "alt": alt[:500],
            "aria": aria[:200],
            "title": title_attr[:200],
        })

        if len(candidates) >= MAX_CANDIDATES:
            break

    return candidates


def inspect_product_page(page, candidate, index):
    started = time.perf_counter()

    try:
        response = page.goto(
            candidate["url"],
            wait_until="domcontentloaded",
            timeout=TIMEOUT,
        )

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=12000,
            )
        except Exception:
            pass

        page.wait_for_timeout(1000)

    except Exception as exc:
        return {
            "index": index,
            "candidate": candidate,
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    title = clean(page.title())

    h1 = ""
    try:
        h1 = clean(
            page.locator("h1").first.inner_text(timeout=3000)
        )
    except Exception:
        pass

    canonical = ""
    canonical_node = soup.find(
        "link",
        rel=lambda value: (
            value and "canonical" in value
            if isinstance(value, list)
            else value == "canonical"
        ),
    )

    if canonical_node:
        canonical = absolute_url(
            page.url,
            canonical_node.get("href"),
        )

    objects = extract_jsonld(soup)
    products = product_jsonld(objects)

    product_data = []

    for product in products:
        brand = product.get("brand")
        if isinstance(brand, dict):
            brand = brand.get("name")
        elif isinstance(brand, list):
            brand = ", ".join(
                clean(
                    item.get("name")
                    if isinstance(item, dict)
                    else item
                )
                for item in brand
            )

        offers = product.get("offers")

        if isinstance(offers, list):
            offers_out = offers[:5]
        elif isinstance(offers, dict):
            offers_out = [offers]
        else:
            offers_out = []

        product_data.append({
            "name": clean(product.get("name")),
            "brand": clean(brand),
            "sku": clean(product.get("sku")),
            "mpn": clean(product.get("mpn")),
            "product_id": clean(
                product.get("productID")
            ),
            "image": (
                product.get("image")
                if isinstance(
                    product.get("image"),
                    (str, list),
                )
                else None
            ),
            "offers": [
                {
                    "price": item.get("price"),
                    "currency": item.get("priceCurrency"),
                    "availability": item.get("availability"),
                    "url": item.get("url"),
                }
                for item in offers_out
                if isinstance(item, dict)
            ],
        })

    text = clean(soup.get_text(" ", strip=True))

    # Useful fallback observations only; no hard-coded product logic.
    prices = PRICE_RE.findall(text)
    sizes = SIZE_RE.findall(text)

    elapsed = round(time.perf_counter() - started, 3)

    status = response.status if response is not None else None

    result = {
        "index": index,
        "candidate": candidate,
        "ok": bool(response and response.status < 400),
        "status": status,
        "url": page.url,
        "elapsed": elapsed,
        "bytes": len(html.encode("utf-8", errors="ignore")),
        "title": title,
        "h1": h1,
        "canonical": canonical,
        "jsonld_objects": len(objects),
        "jsonld_products": product_data,
        "visible_price_examples": prices[:20],
        "visible_size_examples": sizes[:20],
    }

    print(
        f"NOTINO_V6_PRODUCT[{index}]: "
        f"status={status} "
        f"url={page.url} "
        f"title={title!r} "
        f"h1={h1!r} "
        f"jsonld_products={len(product_data)}",
        flush=True,
    )

    for pidx, pdata in enumerate(product_data, 1):
        print(
            f"NOTINO_V6_PRODUCT_DATA[{index}.{pidx}]: "
            f"name={pdata['name']!r} "
            f"brand={pdata['brand']!r} "
            f"sku={pdata['sku']!r} "
            f"mpn={pdata['mpn']!r} "
            f"product_id={pdata['product_id']!r} "
            f"offers={pdata['offers']!r}",
            flush=True,
        )

    return result


def search(query):
    query = clean(query)

    print(
        f"NOTINO_V6_VERSION: {SCRAPER_VERSION}",
        flush=True,
    )
    print(
        f"NOTINO_V6_START: query={query!r}",
        flush=True,
    )

    if not query:
        return []

    search_url = (
        SEARCH_URL
        + "?exps="
        + quote(query)
    )

    report = {
        "diagnostic": True,
        "version": SCRAPER_VERSION,
        "query": query,
        "search_url": search_url,
        "search": None,
        "candidates": [],
        "product_pages": [],
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )

        try:
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                locale="fr-FR",
                viewport={
                    "width": 1365,
                    "height": 900,
                },
            )

            try:
                page = context.new_page()

                started = time.perf_counter()

                response = page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT,
                )

                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=12000,
                    )
                except Exception:
                    pass

                page.wait_for_timeout(1000)

                elapsed = round(
                    time.perf_counter() - started,
                    3,
                )

                status = (
                    response.status
                    if response is not None
                    else None
                )

                print(
                    f"NOTINO_V6_SEARCH: "
                    f"status={status} "
                    f"url={page.url} "
                    f"elapsed={elapsed}s",
                    flush=True,
                )

                if response is None or status >= 400:
                    report["search"] = {
                        "status": status,
                        "url": page.url,
                        "elapsed": elapsed,
                    }
                    return [report]

                candidates = candidate_links(
                    page,
                    query,
                )

                report["search"] = {
                    "status": status,
                    "url": page.url,
                    "elapsed": elapsed,
                    "bytes": len(
                        page.content().encode(
                            "utf-8",
                            errors="ignore",
                        )
                    ),
                }

                report["candidates"] = candidates

                print(
                    f"NOTINO_V6_DISCOVERY: "
                    f"candidates={len(candidates)}",
                    flush=True,
                )

                for index, candidate in enumerate(
                    candidates,
                    1,
                ):
                    print(
                        f"NOTINO_V6_CANDIDATE[{index}]: "
                        f"url={candidate['url']} "
                        f"p_id={candidate['p_id']} "
                        f"text={candidate['text']!r}",
                        flush=True,
                    )

                # Reuse the same browser context, but each product gets
                # a fresh page. No homepage visit is performed.
                for index, candidate in enumerate(
                    candidates,
                    1,
                ):
                    product_page = context.new_page()

                    try:
                        result = inspect_product_page(
                            product_page,
                            candidate,
                            index,
                        )
                        report["product_pages"].append(result)
                    finally:
                        product_page.close()

            finally:
                context.close()

        finally:
            browser.close()

    valid_pages = [
        item
        for item in report["product_pages"]
        if item.get("ok")
    ]

    product_jsonld_count = sum(
        len(item.get("jsonld_products", []))
        for item in valid_pages
    )

    print(
        f"NOTINO_V6_END: "
        f"candidates={len(report['candidates'])} "
        f"opened={len(report['product_pages'])} "
        f"ok_pages={len(valid_pages)} "
        f"jsonld_products={product_jsonld_count}",
        flush=True,
    )

    return [report]


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
