from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

import requests

from app.connectors.legacy_scrapers import LegacyScraperConnector
from scrapers.easycosmetic import scraper


PRODUCT_URL = (
    "https://www.easycosmetic.de/giorgio-armani/acqua-di-gio-homme-profondo/"
    "giorgio-armani-acqua-di-gio-homme-profondo-edp-vapo.aspx"
)


def main() -> int:
    parsed_url = urlparse(PRODUCT_URL)
    if parsed_url.scheme != "https" or parsed_url.hostname != "www.easycosmetic.de":
        raise SystemExit("Refusing non-Easycosmetic URL")

    report: dict[str, object] = {
        "store": "easycosmetic.de",
        "mode": "single product read-only probe",
        "database_accessed": False,
        "catalog_written": False,
        "queue_touched": False,
        "product_url": PRODUCT_URL,
    }
    try:
        # Exactly one HTTP request. No retries, browser fallback, search or discovery.
        response = requests.get(
            PRODUCT_URL,
            headers=scraper.HEADERS,
            timeout=(8, 15),
            allow_redirects=True,
        )
        report["http_status"] = response.status_code
        report["final_url"] = response.url
        if urlparse(response.url).hostname not in {"easycosmetic.de", "www.easycosmetic.de"}:
            report["result"] = "FAIL"
            report["reason"] = "redirect_outside_easycosmetic.de"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1
        if response.status_code != 200:
            report["result"] = "BLOCKED" if response.status_code in {403, 429} else "FAIL"
            report["reason"] = f"http_{response.status_code}"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        raw = scraper._parse_product_html(PRODUCT_URL, response.text)
        if not isinstance(raw, dict):
            report["result"] = "FAIL"
            report["reason"] = "product_parser_returned_no_record"
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 1

        connector = LegacyScraperConnector("easycosmetic", object())
        normalized = connector.parse_raw(raw)
        report.update({
            "name": normalized.get("raw_name"),
            "brand": normalized.get("brand_raw"),
            "size_ml": normalized.get("size_ml"),
            "price": normalized.get("price"),
            "currency": normalized.get("currency"),
            "currency_explicit": normalized.get("currency_explicit"),
            "availability": normalized.get("availability"),
            "gtin": normalized.get("gtin"),
            "product_url": normalized.get("product_url"),
        })
        missing = [
            key for key, valid in (
                ("name", bool(normalized.get("raw_name"))),
                ("brand", bool(normalized.get("brand_raw"))),
                ("size_ml", normalized.get("size_ml") is not None),
                ("price", normalized.get("price") is not None),
                ("explicit_eur", normalized.get("currency") == "EUR" and normalized.get("currency_explicit") is True),
                ("availability", normalized.get("availability") in {"in_stock", "out_of_stock"}),
                ("product_url", bool(normalized.get("product_url"))),
            ) if not valid
        ]
        report["missing_requirements"] = missing
        report["result"] = "PASS" if not missing else "FAIL"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print(f"EASYCOSMETIC_LIVE_CHECK={report['result']}", flush=True)
        return 0 if not missing else 1
    except requests.RequestException as exc:
        report["result"] = "FAIL"
        report["reason"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
