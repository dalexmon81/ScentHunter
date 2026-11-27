from __future__ import annotations

import json
import sys
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

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
        raw_data = raw.get("raw_data") if isinstance(raw.get("raw_data"), dict) else {}
        jsonld = raw_data.get("jsonld_product") if isinstance(raw_data.get("jsonld_product"), dict) else {}
        soup = BeautifulSoup(response.text, "html.parser")
        brand_meta = soup.find(attrs={"itemprop": "brand"})
        brand_meta_text = brand_meta.get("content") or brand_meta.get_text(" ", strip=True) if brand_meta else None
        brand_nodes = []
        for node in soup.select('[class*="brand" i], [id*="brand" i], [itemprop="brand"]')[:12]:
            value = node.get("content") or node.get_text(" ", strip=True)
            value = " ".join(str(value or "").split())
            if value and value not in brand_nodes:
                brand_nodes.append(value[:160])
        report["brand_evidence"] = {
            "parsed_brand": normalized.get("brand_raw"),
            "jsonld_brand": jsonld.get("brand"),
            "jsonld_manufacturer": jsonld.get("manufacturer"),
            "itemprop_brand": brand_meta_text,
            "brand_dom_candidates": brand_nodes,
            "jsonld_keys": sorted(jsonld.keys()),
        }
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
