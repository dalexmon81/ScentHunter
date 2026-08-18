"""
Notino diagnostic V4 for ScentHunter.

Purpose:
- Diagnostic only. No product scraping, validation, seeds or product-specific rules.
- First establish whether Railway can reach Notino.
- Then establish whether a real browser is available in the Railway runtime.
- If Playwright is available, use Chromium and report the exact browser response.
- If Playwright is not available, inspect the runtime for browser executables and
  report exactly what is missing instead of pretending a browser test happened.

This file is intentionally independent from the normal Notino scraper.
It can be loaded by the existing /test-store endpoint.

Test groups:
A  Direct HTTP requests to homepage and search.
B  HTTP session: homepage first, then search.
C  Runtime/browser availability.
D  Real Chromium through Playwright, when available:
   - direct search
   - homepage then search in the same browser context
   - fresh context search
E  Browser response/challenge inspection.

No product-specific URL, name or exception is used.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:
    PlaywrightTimeoutError = Exception
    sync_playwright = None


STORE = "Notino"
BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp"

HTTP_TIMEOUT = 20
BROWSER_TIMEOUT_MS = 30000

SCRAPER_VERSION = "notino-DIAGNOSTIC-2026-08-18-v4"

HEADERS = {
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
    return SEARCH_URL + "?exps=" + quote(str(query or ""))


def page_fingerprint(body):
    body = body or ""
    soup = BeautifulSoup(body, "html.parser")

    title = ""
    h1 = ""

    if soup.title:
        title = clean(soup.title.get_text(" ", strip=True))

    h1_node = soup.select_one("h1")
    if h1_node:
        h1 = clean(h1_node.get_text(" ", strip=True))

    text = clean(body)
    lower = text.lower()

    markers = {
        marker: marker in lower
        for marker in CHALLENGE_MARKERS
    }

    return {
        "title": title,
        "h1": h1,
        "challenge_detected": any(markers.values()),
        "challenge_markers": [
            marker for marker, found in markers.items() if found
        ],
        "html_bytes": len(body.encode("utf-8", errors="ignore")),
        "anchors": len(soup.find_all("a", href=True)),
    }


def interesting_headers(response):
    result = {}

    for name in INTERESTING_HEADERS:
        value = response.headers.get(name)

        if value:
            if name.lower() == "set-cookie":
                value = value[:1000]

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
        "ok": bool(response.ok),
        "status": response.status_code,
        "seconds": round(elapsed, 3),
        "requested_url": (
            response.request.url
            if response.request is not None
            else None
        ),
        "final_url": response.url,
        "history": [
            {
                "status": item.status_code,
                "url": item.url,
                "location": item.headers.get("Location"),
            }
            for item in response.history
        ],
        "headers": interesting_headers(response),
        "cookies": {
            key: value
            for key, value in response.cookies.items()
        },
        "page": page_fingerprint(body),
    }


def http_get(session, label, url):
    started = time.perf_counter()

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=HTTP_TIMEOUT,
            allow_redirects=True,
        )

        elapsed = time.perf_counter() - started

        print(
            "NOTINO_V4_HTTP: "
            f"{label} status={response.status_code} "
            f"url={response.url} bytes={len(response.content)}",
            flush=True,
        )

        return request_snapshot(label, response, elapsed)

    except Exception as exc:
        elapsed = time.perf_counter() - started

        print(
            "NOTINO_V4_HTTP_ERROR: "
            f"{label} {type(exc).__name__}: {exc}",
            flush=True,
        )

        return request_snapshot(
            label,
            None,
            elapsed,
            f"{type(exc).__name__}: {exc}",
        )


def find_browser_executables():
    candidates = [
        ("chromium", shutil.which("chromium")),
        ("chromium-browser", shutil.which("chromium-browser")),
        ("google-chrome", shutil.which("google-chrome")),
        ("google-chrome-stable", shutil.which("google-chrome-stable")),
        ("chrome", shutil.which("chrome")),
        ("msedge", shutil.which("msedge")),
        ("firefox", shutil.which("firefox")),
    ]

    common_paths = [
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chrome",
        "/usr/bin/msedge",
        "/usr/bin/firefox",
    ]

    found = []

    for name, path in candidates:
        if path:
            found.append({
                "name": name,
                "path": path,
                "source": "PATH",
            })

    for path in common_paths:
        if os.path.isfile(path) and os.access(path, os.X_OK):
            if not any(item["path"] == path for item in found):
                found.append({
                    "name": os.path.basename(path),
                    "path": path,
                    "source": "common_path",
                })

    return found


def command_version(path):
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        output = clean(result.stdout or result.stderr)

        return {
            "ok": result.returncode == 0,
            "version": output[:300],
            "returncode": result.returncode,
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


def runtime_diagnostics():
    browsers = find_browser_executables()

    for item in browsers:
        item["version"] = command_version(item["path"])

    playwright_available = sync_playwright is not None

    result = {
        "python": {
            "version": __import__("sys").version.split()[0],
        },
        "playwright": {
            "python_package_available": playwright_available,
        },
        "browsers_found": browsers,
        "environment": {
            "PLAYWRIGHT_BROWSERS_PATH": os.environ.get(
                "PLAYWRIGHT_BROWSERS_PATH"
            ),
            "HOME": os.environ.get("HOME"),
        },
    }

    if playwright_available:
        try:
            with sync_playwright() as playwright:
                chromium = playwright.chromium
                result["playwright"]["chromium_type_available"] = (
                    chromium is not None
                )
        except Exception as exc:
            result["playwright"]["startup_probe_error"] = (
                f"{type(exc).__name__}: {exc}"
            )

    return result


def browser_snapshot(page, response, label, elapsed):
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

    page_info = page_fingerprint(html)
    page_info["title"] = title
    page_info["h1"] = h1

    response_headers = {}

    if response is not None:
        for name in INTERESTING_HEADERS:
            value = response.headers.get(name)

            if value:
                if name.lower() == "set-cookie":
                    value = value[:1000]

                response_headers[name] = value

    status = response.status if response is not None else None

    result = {
        "label": label,
        "ok": bool(response is None or status < 400),
        "status": status,
        "seconds": round(elapsed, 3),
        "final_url": page.url,
        "headers": response_headers,
        "page": page_info,
    }

    print(
        "NOTINO_V4_BROWSER: "
        f"{label} status={status} url={page.url} "
        f"bytes={page_info['html_bytes']}",
        flush=True,
    )

    return result


def browser_goto(page, label, url):
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
            "NOTINO_V4_BROWSER_ERROR: "
            f"{label} {type(exc).__name__}: {exc}",
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
            timeout=15000,
        )
    except PlaywrightTimeoutError:
        pass

    page.wait_for_timeout(1500)

    elapsed = time.perf_counter() - started

    return browser_snapshot(
        page,
        response,
        label,
        elapsed,
    )


def run_browser_test(query):
    result = {
        "available": sync_playwright is not None,
        "stages": [],
    }

    if sync_playwright is None:
        result["error"] = "playwright_python_package_not_installed"

        print(
            "NOTINO_V4_BROWSER: PLAYWRIGHT_PYTHON_PACKAGE_NOT_INSTALLED",
            flush=True,
        )

        return result

    search = query_url(query)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )

            try:
                # Fresh context: search directly.
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="fr-FR",
                    extra_http_headers={
                        "Accept": HEADERS["Accept"],
                        "Accept-Language": HEADERS["Accept-Language"],
                    },
                    viewport={
                        "width": 1365,
                        "height": 900,
                    },
                )

                try:
                    page = context.new_page()

                    result["stages"].append(
                        browser_goto(
                            page,
                            "browser_direct_search",
                            search,
                        )
                    )

                    page.close()
                finally:
                    context.close()

                # Fresh context: homepage first, then search.
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale="fr-FR",
                    extra_http_headers={
                        "Accept": HEADERS["Accept"],
                        "Accept-Language": HEADERS["Accept-Language"],
                    },
                    viewport={
                        "width": 1365,
                        "height": 900,
                    },
                )

                try:
                    page = context.new_page()

                    result["stages"].append(
                        browser_goto(
                            page,
                            "browser_homepage",
                            BASE_URL,
                        )
                    )

                    result["stages"].append(
                        browser_goto(
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
                        }
                        for cookie in context.cookies()
                    ]

                    page.close()
                finally:
                    context.close()

            finally:
                browser.close()

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

        print(
            "NOTINO_V4_BROWSER_FATAL: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    return result


def build_conclusion(report):
    http_tests = report["tests"]["http"]
    runtime = report["tests"]["runtime"]
    browser = report["tests"]["browser"]

    homepage = http_tests["homepage"]
    search = http_tests["search"]
    search_after_homepage = http_tests["search_after_homepage"]

    homepage_status = homepage.get("status")
    search_status = search.get("status")
    session_search_status = search_after_homepage.get("status")

    browser_statuses = [
        stage.get("status")
        for stage in browser.get("stages", [])
        if isinstance(stage, dict)
    ]

    observations = []

    observations.append({
        "http_homepage_status": homepage_status,
        "http_direct_search_status": search_status,
        "http_session_search_status": session_search_status,
        "browser_statuses": browser_statuses,
        "playwright_python_package_available": runtime[
            "playwright"
        ].get("python_package_available"),
        "browser_executables_found": [
            item["path"]
            for item in runtime.get("browsers_found", [])
        ],
    })

    if homepage_status == 403 and search_status == 403:
        observations.append(
            "HTTP_BLOCK_CONFIRMED: Railway requests receive 403 before "
            "the Notino page is available to the parser."
        )

    if (
        session_search_status is not None
        and session_search_status != search_status
    ):
        observations.append(
            "SESSION_RESULT_CHANGED: visiting the homepage first changed "
            "the HTTP search result."
        )

    if browser_statuses and any(
        status is not None and status < 400
        for status in browser_statuses
    ):
        observations.append(
            "REAL_BROWSER_REACHES_NOTINO: at least one Chromium navigation "
            "returned a non-error HTTP status."
        )

    if browser_statuses and all(
        status == 403
        for status in browser_statuses
        if status is not None
    ):
        observations.append(
            "REAL_BROWSER_ALSO_BLOCKED: Chromium itself received 403 on "
            "all recorded navigations."
        )

    if not runtime["playwright"].get("python_package_available"):
        observations.append(
            "BROWSER_TEST_NOT_EXECUTED: the Railway runtime does not have "
            "the Playwright Python package installed."
        )

    if (
        not runtime.get("browsers_found")
        and runtime["playwright"].get("python_package_available")
    ):
        observations.append(
            "NO_SYSTEM_BROWSER_FOUND: Playwright is installed but no "
            "system browser executable was discovered; Chromium launch "
            "will depend on a Playwright-managed browser being installed."
        )

    return observations


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
    # A/B: direct HTTP and HTTP session.
    # ------------------------------------------------------------
    session = requests.Session()

    try:
        homepage = http_get(
            session,
            "A_http_homepage",
            BASE_URL,
        )

        direct_search = http_get(
            session,
            "B_http_direct_search",
            search,
        )

        search_after_homepage = http_get(
            session,
            "C_http_search_after_homepage",
            search,
        )

        report["tests"]["http"] = {
            "homepage": homepage,
            "search": direct_search,
            "search_after_homepage": search_after_homepage,
            "cookies_after": [
                {
                    "name": cookie.name,
                    "domain": cookie.domain,
                    "path": cookie.path,
                }
                for cookie in session.cookies
            ],
        }

    finally:
        session.close()

    # ------------------------------------------------------------
    # D: inspect the actual Railway runtime.
    # ------------------------------------------------------------
    report["tests"]["runtime"] = runtime_diagnostics()

    print(
        "NOTINO_V4_RUNTIME: "
        f"playwright="
        f"{report['tests']['runtime']['playwright'].get('python_package_available')} "
        f"browsers="
        f"{len(report['tests']['runtime'].get('browsers_found', []))}",
        flush=True,
    )

    # ------------------------------------------------------------
    # E: real Chromium, if the runtime can provide it.
    # ------------------------------------------------------------
    report["tests"]["browser"] = run_browser_test(query)

    report["observations"] = build_conclusion(report)

    browser_statuses = [
        stage.get("status")
        for stage in report["tests"]["browser"].get("stages", [])
        if isinstance(stage, dict)
    ]

    print(
        "NOTINO_DIAG_END: "
        f"HTTP_HOME={report['tests']['http']['homepage'].get('status')} "
        f"HTTP_SEARCH={report['tests']['http']['search'].get('status')} "
        f"HTTP_SESSION={report['tests']['http']['search_after_homepage'].get('status')} "
        f"PLAYWRIGHT={report['tests']['runtime']['playwright'].get('python_package_available')} "
        f"BROWSER={browser_statuses}",
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
