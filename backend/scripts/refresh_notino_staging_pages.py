"""Refresh known Notino product pages in the isolated PR #726 staging catalog."""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.services.notino_affiliate import is_valid_notino_affiliate_url
from app.services.notino_phase2_search import search_notino_phase2
from product_matcher import ProductMatcher
from scrapers.notino.scraper import _extract_concentration


_PRODUCTS = (
    ("Rasasi Hawas Ice", "614514331040", "Rasasi", 100, "Eau de Parfum"),
    ("Rayhaan Aquatica", "6297001571330", "Rayhaan", 100, "Eau de Parfum"),
)


def _destination(affiliate_url: str) -> str:
    if not is_valid_notino_affiliate_url(affiliate_url):
        raise ValueError("invalid_notino_affiliate_url")
    target = parse_qs(urlsplit(affiliate_url).query)["url"]
    return target[0]


def _refresh_product(query: str, gtin: str, brand: str, size_ml: int, concentration: str) -> dict:
    matches = [
        row for row in search_notino_phase2(query, limit=100)
        if str(row.get("gtin") or "").strip() == gtin
    ]
    destinations = {_destination(str(row.get("url") or "")) for row in matches}
    product_ids = {
        re.search(r"/p-(\d+)/?$", urlsplit(url).path, re.I).group(1)
        for url in destinations
        if re.search(r"/p-(\d+)/?$", urlsplit(url).path, re.I)
    }
    if len(matches) == 0 or len(product_ids) != 1 or len(destinations) != 1:
        raise ValueError(f"notino_gtin_destination_not_unique:{gtin}")
    destination = next(iter(destinations))
    if ProductMatcher._is_non_fragrance_offer({
        "name": next(row.get("name") for row in matches if row.get("gtin") == gtin),
        "url": destination,
    }):
        raise ValueError(f"notino_destination_is_not_a_bottle:{gtin}")

    import catalog_engine

    item = catalog_engine.refresh_url("notino", destination)
    if not isinstance(item, dict):
        raise RuntimeError(f"notino_product_page_refresh_failed:{gtin}")
    actual_size = item.get("size_ml")
    try:
        actual_size = float(actual_size)
        price = float(item.get("price_num"))
    except (TypeError, ValueError):
        raise RuntimeError(f"notino_product_page_missing_price_or_size:{gtin}") from None
    final_url = str(item.get("url") or "")
    expected_id = next(iter(product_ids))
    final_match = re.search(r"/p-(\d+)/?$", urlsplit(final_url).path, re.I)
    if (
        str(item.get("brand") or "").casefold() != brand.casefold()
        or abs(actual_size - size_ml) > 0.01
        or _extract_concentration(item.get("concentration")) != concentration
        or item.get("availability") not in {"in stock", "out of stock"}
        or price <= 0
        or not final_match
        or final_match.group(1) != expected_id
    ):
        raise RuntimeError(f"notino_product_page_identity_mismatch:{gtin}")
    return {
        "query": query,
        "gtin": gtin,
        "brand": brand,
        "size_ml": actual_size,
        "concentration": item["concentration"],
        "price": price,
        "availability": item["availability"],
        "url": final_url,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-pr726-staging", action="store_true", required=True)
    args = parser.parse_args()
    if not args.confirm_pr726_staging:
        parser.error("this command is restricted to PR #726 staging")
    if os.environ.get("FLY_APP_NAME") != "scenthunter-pr726-staging":
        raise RuntimeError("refusing to refresh Notino pages outside PR #726 staging")
    catalog_path = Path(os.environ.get("SCENTHUNTER_CATALOG_DB", "")).resolve()
    phase2_path = Path(os.environ.get(
        "NOTINO_PHASE2_DATABASE", "/data/notino-phase2/catalog.sqlite3"
    )).resolve()
    if not catalog_path.is_relative_to("/data") or not phase2_path.is_relative_to("/data/notino-phase2"):
        raise RuntimeError("refusing to write outside isolated staging volumes")
    for product in _PRODUCTS:
        print(_refresh_product(*product), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
