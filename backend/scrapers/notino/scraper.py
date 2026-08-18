"""
Notino diagnostic V3 for ScentHunter.

Purpose:
- Do NOT scrape or validate products.
- Do NOT contain product-specific rules, seeds, URLs or exceptions.
- Compare the HTTP path that previously worked with the browser path used
  by the working Notino discovery scraper.
- The same diagnostic can be called with any query through search(query).

Stages:
1. requests + Chrome 124 headers used by the working discovery scraper.
2. requests + Chrome 126 headers used by the previous diagnostic.
3. requests session after first visiting the homepage.
4. Playwright browser, using the same browser configuration as the working
   Notino discovery scraper.
5. Playwright browser after the homepage has been opened, then search.

Every stage reports:
- status
- final URL
- elapsed time
- response size
- redirect chain
- relevant response headers
- cookies
- title / h1
- Cloudflare/challenge markers
- whether product-looking links were present

The file intentionally returns diagnostic observations, not fake products.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception
    sync_playwright = None


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"
TIMEOUT = 20
BROWSER_TIMEOUT_MS = 30000

SCRAPER_VERSION = "notino-DIAGNOSTIC-2026-08-18-v3"

# This is the exact UA/header family used by the working
# Notino_FR_CORRETTO_DISCOVERY scraper.
WORKING_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

# This is the header family used by the previous diagnostic versions.
PREVIOUS_DIAGNOSTIC_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
}

PRODUCT_ID_RE = re.compile(r"/p-\d+(?:/|$)", re.I)

CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "challenge-platform",
    "checking your browser",
    "verify you are human",
    "performing security verification",
    "enable javascript and cookies",
    "attention required",
)

INTERESTING_HEADERS = (
    "server",
    "cf-ray",
    "cf-cache-status",
    "cf-mitigated",
    "content-type",
    "location",
    "set-cookie",
    "cache-control",
    "via",
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def query_url(query):
    return SEARCH_URL + "?exps=" + requests.utils.quote(str(query or ""))


def detect_page(body):
    text = clean(body)
    soup = BeautifulSoup(body or "", "html.parser")

    title = clean(soup.title.get_text(" ", strip=True)) if soup.title else ""
    h1_node = soup.select_one("h1")
    h1 = clean(h1_node.get_text(" ", strip=True)) if h1_node else ""

    lower = text.lower()

    markers = {
        marker: marker in lower
        for marker in CHALLENGE_MARKERS
    }

    challenge = any(markers.values())

    product_links = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        if not href:
            continue

        absolute = urljoin(BASE_URL, href).split("#", 1)[0]

        if not absolute.startswith(BASE_URL):
            continue

        if not PRODUCT_ID_RE.search(absolute):
            continue

        if absolute.lower() in seen:
            continue

        seen.add(absolute.lower())
        product_links.append(absolute)

    return {
        "title": title,
        "h1": h1,
        "challenge_detected": challenge,
        "challenge_markers": [
            marker for marker, present in markers.items() if present
        ],
        "html_bytes": len(body.encode("utf-8", errors="ignore")),
        "anchors": len(soup.find_all("a", href=True)),
        "product_id_links": len(product_links),
        "product_id_examples": product_links[:10],
    }


def response_headers(response):
    result = {}

    for name in INTERESTING_HEADERS:
        value = response.headers.get(name)
        if value:
            if name.lower() == "set-cookie":
                value = value[:800]
            result[name] = value

    return result


def request_snapshot(label, response, elapsed, error=None):
    if error is not None or response is None:
        return {
            "label": label,
            "ok": False,
            "seconds": round(elapsed, 3),
            "error": error or "no_response",
        }

    body = response.text or ""

    return {
        "label": label,
        "ok": response.ok,
        "status": response.status_code,
        "seconds": round(elapsed, 3),
        "requested_url": response.request.url if response.request else None,
        "final_url": response.url,
        "history": [
            {
                "status": item.status_code,
                "url": item.url,
                "location": item.headers.get("Location"),
            }
            for item in response.history
        ],
        "headers": response_headers(response),
        "cookies": {
            key: value
            for key, value in response.cookies.items()
        },
        "page": detect_page(body),
    }


def requests_get(session, label, url, headers, timeout=TIMEOUT):
    started = time.perf_counter()

    try:
        response = session.get(
            url,
            headers=headers,
            timeout=timeout,
            allow_redirects=True,
        )
        elapsed = time.perf_counter() - started

        print(
            f"NOTINO_V3_HTTP: {label} status={response.status_code} "
            f"url={response.url} bytes={len(response.content)}",
            flush=True,
        )

        return request_snapshot(label, response, elapsed)

    except Exception as exc:
        elapsed = time.perf_counter() - started

        print(
            f"NOTINO_V3_HTTP_ERROR: {label} "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        return request_snapshot(
            label,
            None,
            elapsed,
            f"{type(exc).__name__}: {exc}",
        )


def playwright_context(playwright):
    browser = playwright.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
        ],
    )

    context = browser.new_context(
        user_agent=WORKING_HEADERS["User-Agent"],
        locale="fr-FR",
        extra_http_headers={
            "Accept": WORKING_HEADERS["Accept"],
            "Accept-Language": WORKING_HEADERS["Accept-Language"],
        },
        viewport={
            "width": 1365,
            "height": 900,
        },
    )

    return browser, context


def browser_page_snapshot(page, response, label, elapsed):
    try:
        html = page.content()
    except Exception:
        html = ""

    title = ""
    h1 = ""

    try:
        title = clean(page.title())
    except Exception:
        pass

    try:
        h1 = clean(
            page.locator("h1").first.inner_text(timeout=2000)
        )
    except Exception:
        pass

    page_info = detect_page(html)
    page_info["title"] = title
    page_info["h1"] = h1

    headers = {}
    if response is not None:
        for name in INTERESTING_HEADERS:
            value = response.headers.get(name)
            if value:
                if name.lower() == "set-cookie":
                    value = value[:800]
                headers[name] = value

    status = response.status if response is not None else None
    final_url = page.url

    print(
        f"NOTINO_V3_BROWSER: {label} status={status} "
        f"url={final_url} bytes={len(html.encode('utf-8', errors='ignore'))}",
        flush=True,
    )

    return {
        "label": label,
        "ok": bool(response is None or status < 400),
        "status": status,
        "seconds": round(elapsed, 3),
        "final_url": final_url,
        "headers": headers,
        "page": page_info,
    }


def playwright_goto(page, label, url):
    started = time.perf_counter()

    try:
        response = page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=BROWSER_TIMEOUT_MS,
        )
    except Exception as exc:
        elapsed = time.perf_counter() - started

        print(
            f"NOTINO_V3_BROWSER_ERROR: {label} "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        return {
            "label": label,
            "ok": False,
            "seconds": round(elapsed, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "final_url": page.url,
        }

    try:
        page.wait_for_load_state(
            "networkidle",
            timeout=min(BROWSER_TIMEOUT_MS, 15000),
        )
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(1200)

    elapsed = time.perf_counter() - started

    return browser_page_snapshot(
        page,
        response,
        label,
        elapsed,
    )


def browser_stage(query):
    result = {
        "available": sync_playwright is not None,
        "stages": [],
    }

    if sync_playwright is None:
        result["error"] = "playwright_not_installed"
        print(
            "NOTINO_V3_BROWSER: PLAYWRIGHT_NOT_INSTALLED",
            flush=True,
        )
        return result

    search = query_url(query)

    try:
        with sync_playwright() as playwright:
            browser, context = playwright_context(playwright)

            try:
                page = context.new_page()

                # Browser request WITHOUT a homepage first.
                result["stages"].append(
                    playwright_goto(
                        page,
                        "browser_search_direct",
                        search,
                    )
                )

                # Fresh browser context: homepage first, then search.
                page.close()

                page = context.new_page()

                result["stages"].append(
                    playwright_goto(
                        page,
                        "browser_homepage",
                        BASE_URL,
                    )
                )

                result["stages"].append(
                    playwright_goto(
                        page,
                        "browser_search_after_homepage",
                        search,
                    )
                )

                result["cookies_after"] = [
                    {
                        "name": cookie.get("name"),
                        "domain": cookie.get("domain"),
                        "path": cookie.get("path"),
                        "expires": cookie.get("expires"),
                    }
                    for cookie in context.cookies()
                ]

                page.close()

            finally:
                browser.close()

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        print(
            f"NOTINO_V3_BROWSER_FATAL: {type(exc).__name__}: {exc}",
            flush=True,
        )

    return result


def search(query):
    query = clean(query)

    print(
        f"NOTINO_DIAG_VERSION: {SCRAPER_VERSION}",
        flush=True,
    )
    print(
        f"NOTINO_DIAG_START: query={query!r}",
        flush=True,
    )

    if not query:
        return [{
            "diagnostic": True,
            "scraper_version": SCRAPER_VERSION,
            "error": "empty_query",
        }]

    search = query_url(query)

    report = {
        "diagnostic": True,
        "scraper_version": SCRAPER_VERSION,
        "query": query,
        "search_url": search,
        "tests": {},
    }

    # ------------------------------------------------------------
    # TEST A: exact HTTP header family from the working discovery file.
    # ------------------------------------------------------------
    session_a = requests.Session()

    try:
        report["tests"]["A_requests_working_headers"] = requests_get(
            session_a,
            "A_requests_working_headers",
            search,
            WORKING_HEADERS,
        )
    finally:
        session_a.close()

    # ------------------------------------------------------------
    # TEST B: exact HTTP header family from the previous diagnostic.
    # ------------------------------------------------------------
    session_b = requests.Session()

    try:
        report["tests"]["B_requests_previous_diagnostic_headers"] = (
            requests_get(
                session_b,
                "B_requests_previous_diagnostic_headers",
                search,
                PREVIOUS_DIAGNOSTIC_HEADERS,
            )
        )
    finally:
        session_b.close()

    # ------------------------------------------------------------
    # TEST C: working headers, homepage first, then search.
    # This checks whether a session/cookie established by the homepage
    # changes the result.
    # ------------------------------------------------------------
    session_c = requests.Session()

    try:
        homepage = requests_get(
            session_c,
            "C1_requests_working_headers_homepage",
            BASE_URL,
            WORKING_HEADERS,
        )

        search_after_homepage = requests_get(
            session_c,
            "C2_requests_working_headers_search_after_homepage",
            search,
            WORKING_HEADERS,
        )

        report["tests"]["C_requests_homepage_then_search"] = {
            "homepage": homepage,
            "search": search_after_homepage,
            "session_cookies_after": [
                {
                    "name": cookie.name,
                    "domain": cookie.domain,
                    "path": cookie.path,
                }
                for cookie in session_c.cookies
            ],
        }

    finally:
        session_c.close()

    # ------------------------------------------------------------
    # TEST D/E: real Chromium, the path used by the working scraper.
    # ------------------------------------------------------------
    report["tests"]["D_E_playwright"] = browser_stage(query)

    # Compact conclusion generated only from observations.
    observations = []

    a = report["tests"]["A_requests_working_headers"]
    b = report["tests"]["B_requests_previous_diagnostic_headers"]
    c = report["tests"]["C_requests_homepage_then_search"]
    browser = report["tests"]["D_E_playwright"]

    def status_of(item):
        return item.get("status") if isinstance(item, dict) else None

    a_status = status_of(a)
    b_status = status_of(b)
    c_status = status_of(c.get("search", {}))

    browser_statuses = [
        stage.get("status")
        for stage in browser.get("stages", [])
        if isinstance(stage, dict)
    ]

    observations.append({
        "requests_working_headers_status": a_status,
        "requests_previous_diagnostic_status": b_status,
        "requests_homepage_then_search_status": c_status,
        "playwright_statuses": browser_statuses,
    })

    if a_status == 200 and b_status == 403:
        observations.append(
            "DIFFERENCE_FOUND: the header families produce different HTTP results."
        )

    if c_status == 200 and a_status != 200:
        observations.append(
            "SESSION_EFFECT_FOUND: homepage-before-search changes the HTTP result."
        )

    if any(status is not None and status < 400 for status in browser_statuses):
        observations.append(
            "BROWSER_PATH_AVAILABLE: Chromium obtained a non-error response."
        )

    if any(status == 403 for status in browser_statuses):
        observations.append(
            "BROWSER_PATH_403: Chromium itself received a 403/challenge."
        )

    if not observations[1:]:
        observations.append(
            "NO_SINGLE_CAUSE_PROVEN: compare the stage-by-stage status, headers and challenge markers."
        )

    report["observations"] = observations

    print(
        "NOTINO_DIAG_END: "
        f"A={a_status} B={b_status} C={c_status} "
        f"PLAYWRIGHT={browser_statuses}",
        flush=True,
    )

    # /test-store expects a list.
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
