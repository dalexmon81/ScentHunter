from __future__ import annotations

import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.connectors.legacy_scrapers import LegacyScraperConnector
from scrapers.perfumemarket import scraper


PRODUCT_URL = "https://perfumemarket.eu/products/rasasi-hawas-london-100ml-edp"


def main() -> int:
    session = requests.Session()
    try:
        record = scraper.extract_product_page(
            session,
            PRODUCT_URL,
            query="Rasasi Hawas London",
        )
    finally:
        session.close()

    if not isinstance(record, dict):
        raise SystemExit("PERFUMEMARKET_LIVE_RESULT=FAIL: product page could not be parsed")

    parsed = LegacyScraperConnector("perfumemarket", scraper).parse_raw(record)
    expected = {
        "currency": "EUR",
        "currency_explicit": True,
        "availability": "in_stock",
        "gtin": "614514465059",
        "size_ml": 100,
        "concentration": "Eau de Parfum",
        "product_url": PRODUCT_URL,
    }
    try:
        live_price = Decimal(str(parsed.get("price") or ""))
    except InvalidOperation:
        raise SystemExit("PERFUMEMARKET_LIVE_RESULT=FAIL: invalid live price")
    if live_price <= 0:
        raise SystemExit("PERFUMEMARKET_LIVE_RESULT=FAIL: non-positive live price")
    print(f"price={live_price}")

    for key, value in expected.items():
        actual = parsed.get(key)
        if actual != value:
            raise SystemExit(
                f"PERFUMEMARKET_LIVE_RESULT=FAIL: {key} expected {value!r}, got {actual!r}"
            )
        print(f"{key}={actual}")

    print("PERFUMEMARKET_LIVE_RESULT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
