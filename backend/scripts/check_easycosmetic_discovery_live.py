from __future__ import annotations

import json
import sys
from urllib.parse import quote_plus, urlparse

import requests
from bs4 import BeautifulSoup

from scrapers import easycosmetic as scraper


QUERY = "Dior"
SEARCH_URL = scraper.SEARCH_URL.format(quote_plus(QUERY))


def main() -> int:
    report: dict[str, object] = {
        "store": "easycosmetic.de",
        "mode": "single search-page discovery probe",
        "query": QUERY,
        "http_requests_allowed": 1,
        "product_pages_fetched": 0,
        "database_accessed": False,
        "catalog_written": False,
        "queue_touched": False,
        "search_url": SEARCH_URL,
    }
    try:
        # Exactly one request: inspect the search result page only.
        # Do not fetch candidate product pages, retry, or use browser fallback.
        response = requests.get(
            SEARCH_URL,
            headers=scraper.HEADERS,
            timeout=(8, 15),
            allow_redirects=True,
        )
        report["http_status"] = response.status_code
        report["final_url"] = response.url
        final = urlparse(response.url)
        if final.scheme != "https" or final.hostname not in {"easycosmetic.de", "www.easycosmetic.de"}:
            report["result"] = "FAIL"
            report["reason"] = "redirect_outside_easycosmetic_de"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        if response.status_code in {403, 429}:
            report["result"] = "BLOCKED"
            report["reason"] = f"http_{response.status_code}"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            print("EASYCOSMETIC_DISCOVERY_CHECK=BLOCKED", flush=True)
            return 1
        if response.status_code != 200:
            report["result"] = "FAIL"
            report["reason"] = f"http_{response.status_code}"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        soup = BeautifulSoup(response.text, "html.parser")
        candidates = scraper._extract_candidate_links(soup, QUERY)
        report["candidate_count"] = len(candidates)
        report["candidates"] = [
            {"name": item.get("name"), "url": item.get("url")}
            for item in candidates[:10]
        ]
        report["result"] = "PASS" if candidates else "FAIL"
        if not candidates:
            report["reason"] = "search_page_returned_no_product_candidates"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"EASYCOSMETIC_DISCOVERY_CHECK={report['result']}", flush=True)
        return 0 if candidates else 1
    except requests.RequestException as exc:
        report["result"] = "FAIL"
        report["reason"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
