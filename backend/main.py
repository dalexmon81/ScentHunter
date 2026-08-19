from __future__ import annotations

import json
import logging
import sys
from typing import Any

import requests
from bs4 import BeautifulSoup

from scrapers.notino import scraper as notino

LOGGER = logging.getLogger(__name__)

MAX_CANDIDATES = 80
MAX_PRODUCT_PAGES = 20


def _clean(value: Any) -> str:
    return notino.clean(value)


def _query_score(query: str, *values: Any) -> int:
    query_tokens = notino._discovery_tokens(query)
    if not query_tokens:
        return 0
    text = " ".join(_clean(value) for value in values if value not in (None, ""))
    text_tokens = notino._discovery_tokens(text)
    return len(query_tokens & text_tokens)


def _browser_search(query: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "attempted": False,
        "status": None,
        "final_url": None,
        "html_bytes": 0,
        "raw_link_count": 0,
        "candidate_count": 0,
        "candidate_urls": [],
        "error": None,
    }

    if notino.sync_playwright is None:
        report["error"] = "playwright_not_installed"
        return report

    report["attempted"] = True
    browser = None

    try:
        with notino.sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
            )
            context = browser.new_context(
                user_agent=notino.HEADERS["User-Agent"],
                locale="fr-FR",
                extra_http_headers={"Accept-Language": notino.HEADERS["Accept-Language"]},
                viewport={"width": 1365, "height": 900},
            )
            page = context.new_page()

            response = page.goto(
                notino._search_pages(query)[0],
                wait_until="domcontentloaded",
                timeout=notino.DEFAULT_TIMEOUT_MS,
            )

            report["status"] = response.status if response is not None else None
            report["final_url"] = page.url

            try:
                page.wait_for_load_state(
                    "networkidle",
                    timeout=min(notino.DEFAULT_TIMEOUT_MS, 15000),
                )
            except notino.PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(1000)
            html = page.content()
            report["html_bytes"] = len(html.encode("utf-8"))

            raw_links = notino._diagnostic_raw_links(html)
            report["raw_link_count"] = len(raw_links)

            # Uses the real generic Notino discovery logic.
            candidates = notino._candidate_product_urls(html, query)
            candidates = list(dict.fromkeys(candidates))[:MAX_CANDIDATES]

            report["candidate_count"] = len(candidates)
            report["candidate_urls"] = candidates

    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass

    return report


def _inspect_product(
    session: requests.Session,
    url: str,
    query: str,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "url": url,
        "status": None,
        "final_url": None,
        "html_bytes": 0,
        "h1": "",
        "jsonld_names": [],
        "query_matches": [],
        "decision": "rejected",
        "reason": "",
    }

    try:
        response = session.get(
            url,
            headers=notino.HEADERS,
            timeout=min(notino.TIMEOUT, 8),
            allow_redirects=True,
        )

        entry["status"] = response.status_code
        entry["final_url"] = response.url
        entry["html_bytes"] = len(
            (response.text or "").encode("utf-8")
        )

        html = response.text if response.status_code < 400 else None

        if not html and notino.BROWSER_ENABLED:
            entry["reason"] = "product_page_unavailable"
            return entry

        if not html:
            html = notino._fetch_product_with_playwright(url)

        if not html:
            entry["reason"] = "product_page_unavailable"
            return entry

        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        h1_name = _clean(h1.get_text(" ", strip=True)) if h1 else ""
        entry["h1"] = h1_name

        data_list = notino._parse_json_ld(soup)
        entry["jsonld_names"] = [
            _clean(obj.get("name"))
            for obj in data_list
            if isinstance(obj, dict) and _clean(obj.get("name"))
        ]

        checks = []
        seen_names = set()

        for name in [h1_name, *entry["jsonld_names"]]:
            name = _clean(name)
            if not name or name in seen_names:
                continue

            seen_names.add(name)

            checks.append(
                {
                    "name": name,
                    "match": notino.matches(name, query),
                    "score": _query_score(query, name),
                }
            )

        entry["query_matches"] = checks

        if any(item["match"] for item in checks):
            entry["decision"] = "accepted"
            entry["reason"] = "product_identity_match"
        else:
            entry["reason"] = "no_product_identity_match"

    except requests.RequestException as exc:
        entry["reason"] = (
            f"product_request_error: {type(exc).__name__}: {exc}"
        )
    except Exception as exc:
        entry["reason"] = (
            f"product_parse_error: {type(exc).__name__}: {exc}"
        )

    return entry


def diagnose(query: str) -> dict[str, Any]:
    query = _clean(query)

    report: dict[str, Any] = {
        "query": query,
        "search_url": notino._search_pages(query)[0] if query else "",
        "browser_discovery": {},
        "candidates_considered": 0,
        "product_pages": [],
        "final_results": [],
    }

    if not query:
        report["error"] = "empty_query"
        return report

    browser = _browser_search(query)
    report["browser_discovery"] = browser

    candidates = browser.get("candidate_urls") or []
    candidates = list(dict.fromkeys(candidates))

    # Generic ranking only. No product, brand, seed or URL exceptions.
    candidates.sort(
        key=lambda url: _query_score(query, url),
        reverse=True,
    )

    candidates = candidates[:MAX_PRODUCT_PAGES]
    report["candidates_considered"] = len(candidates)

    session = requests.Session()

    try:
        for url in candidates:
            report["product_pages"].append(
                _inspect_product(session, url, query)
            )
    finally:
        session.close()

    report["final_results"] = [
        item
        for item in report["product_pages"]
        if item.get("decision") == "accepted"
    ]

    return report


def main() -> int:
    if len(sys.argv) < 2:
        print(
            'Usage: python backend/main_diagnostic.py "PRODUCT QUERY"'
        )
        return 2

    query = " ".join(sys.argv[1:]).strip()

    print(
        json.dumps(
            diagnose(query),
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
