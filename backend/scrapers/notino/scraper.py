"""
Notino diagnostic V7.

Goal: determine which browser navigation pattern is accepted by Notino
for a product page after direct search discovery.

No product-specific names, URLs, seeds or exceptions are embedded.
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
SCRAPER_VERSION = "notino-DIAGNOSTIC-2026-08-18-v7"

P_ID_RE = re.compile(r"/p-(\d+)(?:/|$)", re.I)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def abs_url(page_url, href):
    return urljoin(page_url, href).split("#", 1)[0]


def internal(url):
    host = urlparse(url).netloc.lower()
    return host == "notino.fr" or host.endswith(".notino.fr")


def product_candidates(page):
    soup = BeautifulSoup(page.content(), "html.parser")
    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        url = abs_url(page.url, a["href"])
        if not url or not internal(url):
            continue

        path = urlparse(url).path.rstrip("/") + "/"
        match = P_ID_RE.search(path)

        # Generic product-page signal: explicit Notino product ID.
        if not match:
            continue

        if url.lower() in seen:
            continue

        seen.add(url.lower())
        out.append({
            "url": url,
            "p_id": match.group(1),
            "text": clean(a.get_text(" ", strip=True))[:400],
            "alt": clean(
                a.find("img").get("alt")
                if a.find("img")
                else ""
            )[:400],
        })

    return out


def page_probe(page, label, url, mode):
    started = time.perf_counter()
    response = None
    error = None

    try:
        if mode == "goto":
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=TIMEOUT,
            )
        elif mode == "reload":
            response = page.reload(
                wait_until="domcontentloaded",
                timeout=TIMEOUT,
            )
        else:
            raise ValueError(mode)

        try:
            page.wait_for_load_state(
                "networkidle",
                timeout=8000,
            )
        except Exception:
            pass

        page.wait_for_timeout(800)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    elapsed = round(time.perf_counter() - started, 3)

    html = ""
    try:
        html = page.content()
    except Exception:
        pass

    soup = BeautifulSoup(html, "html.parser")
    title = ""
    h1 = ""

    try:
        title = clean(page.title())
    except Exception:
        pass

    h1_node = soup.find("h1")
    if h1_node:
        h1 = clean(h1_node.get_text(" ", strip=True))

    result = {
        "label": label,
        "mode": mode,
        "status": response.status if response else None,
        "url": page.url,
        "elapsed": elapsed,
        "bytes": len(html.encode("utf-8", errors="ignore")),
        "title": title,
        "h1": h1,
        "error": error,
    }

    print(
        f"NOTINO_V7_PROBE: {label} "
        f"status={result['status']} "
        f"url={result['url']} "
        f"bytes={result['bytes']} "
        f"title={title!r}",
        flush=True,
    )

    return result


def click_probe(page, candidate):
    started = time.perf_counter()
    response = None
    error = None

    try:
        locator = page.locator(
            f'a[href="{candidate["url"]}"]'
        ).first

        if locator.count() == 0:
            # Search page can normalize/encode the href.
            locator = page.locator(
                "a[href*='/p-"
                + candidate["p_id"]
                + "/']"
            ).first

        if locator.count() == 0:
            raise RuntimeError("candidate_link_not_found")

        response = locator.click(
            timeout=10000,
            no_wait_after=True,
        )

        page.wait_for_timeout(2500)

    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    elapsed = round(time.perf_counter() - started, 3)

    html = ""
    try:
        html = page.content()
    except Exception:
        pass

    title = ""
    try:
        title = clean(page.title())
    except Exception:
        pass

    result = {
        "label": "same_page_click",
        "mode": "click",
        "status": (
            response.status
            if response is not None
            else None
        ),
        "url": page.url,
        "elapsed": elapsed,
        "bytes": len(
            html.encode("utf-8", errors="ignore")
        ),
        "title": title,
        "error": error,
    }

    print(
        f"NOTINO_V7_PROBE: same_page_click "
        f"status={result['status']} "
        f"url={result['url']} "
        f"bytes={result['bytes']} "
        f"title={title!r}",
        flush=True,
    )

    return result


def new_context(pw):
    return pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )


def context_args():
    return {
        "user_agent": (
            "Mozilla/5.0 (X11; Linux x86_64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "locale": "fr-FR",
        "viewport": {
            "width": 1365,
            "height": 900,
        },
    }


def search_and_get_candidates(browser, search_url):
    context = browser.new_context(**context_args())
    page = context.new_page()

    try:
        response = page.goto(
            search_url,
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

        page.wait_for_timeout(1000)

        print(
            f"NOTINO_V7_SEARCH: status="
            f"{response.status if response else None} "
            f"url={page.url}",
            flush=True,
        )

        return context, page, product_candidates(page)

    except Exception:
        page.close()
        context.close()
        raise


def run_variant(browser, candidate, variant):
    context = browser.new_context(**context_args())
    page = context.new_page()

    try:
        if variant == "fresh_goto":
            return [
                page_probe(
                    page,
                    "fresh_context_direct_product",
                    candidate["url"],
                    "goto",
                )
            ]

        if variant == "fresh_goto_no_slash":
            url = candidate["url"].rstrip("/")
            return [
                page_probe(
                    page,
                    "fresh_context_product_without_trailing_slash",
                    url,
                    "goto",
                )
            ]

        if variant == "search_then_goto":
            search_url = (
                SEARCH_URL
                + "?exps="
                + quote(candidate["query"])
            )

            page_probe(
                page,
                "same_context_search",
                search_url,
                "goto",
            )

            return [
                page_probe(
                    page,
                    "same_context_search_then_product",
                    candidate["url"],
                    "goto",
                )
            ]

        if variant == "search_then_click":
            search_url = (
                SEARCH_URL
                + "?exps="
                + quote(candidate["query"])
            )

            page_probe(
                page,
                "search_before_click",
                search_url,
                "goto",
            )

            return [click_probe(page, candidate)]

        raise ValueError(variant)

    finally:
        page.close()
        context.close()


def search(query):
    query = clean(query)

    print(
        f"NOTINO_V7_VERSION: {SCRAPER_VERSION}",
        flush=True,
    )
    print(
        f"NOTINO_V7_START: query={query!r}",
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
        "candidates": [],
        "probes": [],
    }

    with sync_playwright() as pw:
        browser = new_context(pw)

        try:
            search_context, search_page, candidates = (
                search_and_get_candidates(
                    browser,
                    search_url,
                )
            )

            try:
                # Use the first two generic product-ID candidates only.
                selected = candidates[:2]

                for candidate in selected:
                    candidate["query"] = query

                report["candidates"] = selected

                for i, candidate in enumerate(
                    selected,
                    1,
                ):
                    print(
                        f"NOTINO_V7_CANDIDATE[{i}]: "
                        f"p_id={candidate['p_id']} "
                        f"url={candidate['url']} "
                        f"text={candidate['text']!r}",
                        flush=True,
                    )

            finally:
                search_page.close()
                search_context.close()

            # Each variant is isolated so one anti-bot response cannot
            # contaminate the next test.
            for candidate in report["candidates"]:
                for variant in (
                    "fresh_goto",
                    "fresh_goto_no_slash",
                    "search_then_goto",
                    "search_then_click",
                ):
                    print(
                        f"NOTINO_V7_VARIANT: "
                        f"p_id={candidate['p_id']} "
                        f"variant={variant}",
                        flush=True,
                    )

                    try:
                        probes = run_variant(
                            browser,
                            candidate,
                            variant,
                        )

                        report["probes"].extend(
                            {
                                **probe,
                                "candidate": candidate,
                            }
                            for probe in probes
                        )

                    except Exception as exc:
                        print(
                            "NOTINO_V7_VARIANT_ERROR: "
                            f"p_id={candidate['p_id']} "
                            f"variant={variant} "
                            f"{type(exc).__name__}: {exc}",
                            flush=True,
                        )

        finally:
            browser.close()

    print(
        f"NOTINO_V7_END: "
        f"candidates={len(report['candidates'])} "
        f"probes={len(report['probes'])}",
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
