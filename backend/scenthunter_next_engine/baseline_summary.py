"""Build a compact, read-only Phase 0 quality summary CSV."""
from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from .baseline_report import (
    SUPPORTED_STORES,
    VALID_STOCK,
    generate as generate_offer_baseline,
)

SUMMARY_COLUMNS = (
    "store",
    "catalog_product_count",
    "total_offers",
    "offers_with_valid_price",
    "valid_price_pct",
    "offers_with_valid_url",
    "valid_url_pct",
    "offers_with_valid_stock",
    "valid_stock_pct",
    "matched_match_count",
    "ambiguous_match_count",
    "unresolved_match_count",
)


def summarize_rows(rows, catalog_product_count: int) -> list[dict]:
    totals = {
        store: {
            "total_offers": 0,
            "offers_with_valid_price": 0,
            "offers_with_valid_url": 0,
            "offers_with_valid_stock": 0,
            "matched_match_count": 0,
            "ambiguous_match_count": 0,
            "unresolved_match_count": 0,
        }
        for store in SUPPORTED_STORES
    }
    for row in rows:
        store = str(row.get("store") or "").strip().lower()
        if store not in totals:
            raise ValueError(f"Unexpected retailer in baseline: {store!r}")
        item = totals[store]
        item["total_offers"] += 1
        try:
            price_ok = float(row.get("price")) > 0 and len(str(row.get("currency") or "").strip()) == 3
        except (TypeError, ValueError):
            price_ok = False
        url = str(row.get("offer_url") or "").strip()
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            url_ok = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except ValueError:
            url_ok = False
        stock_ok = str(row.get("availability") or "").strip().lower() in VALID_STOCK
        item["offers_with_valid_price"] += int(price_ok)
        item["offers_with_valid_url"] += int(url_ok)
        item["offers_with_valid_stock"] += int(stock_ok)
        status = str(row.get("match_status") or "").strip().lower()
        if status == "matched":
            item["matched_match_count"] += 1
        elif status == "ambiguous":
            item["ambiguous_match_count"] += 1
        elif status == "unresolved":
            item["unresolved_match_count"] += 1
        else:
            raise ValueError(f"Unknown match status: {status!r}")

    output = []
    aggregate = {key: 0 for key in next(iter(totals.values()))}
    for store in SUPPORTED_STORES:
        item = totals[store]
        count = item["total_offers"]
        if count == 0:
            raise ValueError(f"No offers for required active retailer: {store}")
        for key, value in item.items():
            aggregate[key] += value
        output.append(_summary_row(store, item, catalog_product_count))

    output.append(_summary_row("TOTAL", aggregate, catalog_product_count))
    return output


def _summary_row(store: str, item: dict, catalog_product_count: int) -> dict:
    count = item["total_offers"]
    pct = lambda key: round(100 * item[key] / count, 2) if count else 0.0
    return {
        "store": store,
        "catalog_product_count": catalog_product_count,
        "total_offers": item["total_offers"],
        "offers_with_valid_price": item["offers_with_valid_price"],
        "valid_price_pct": pct("offers_with_valid_price"),
        "offers_with_valid_url": item["offers_with_valid_url"],
        "valid_url_pct": pct("offers_with_valid_url"),
        "offers_with_valid_stock": item["offers_with_valid_stock"],
        "valid_stock_pct": pct("offers_with_valid_stock"),
        "matched_match_count": item["matched_match_count"],
        "ambiguous_match_count": item["ambiguous_match_count"],
        "unresolved_match_count": item["unresolved_match_count"],
    }


def generate_summary(catalog_path: Path, db_path: Path, output_path: Path) -> dict:
    """Generate offer baseline in a temp file, then export aggregate metrics."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="scenthunter-phase0-summary-") as temp_dir:
        offer_path = Path(temp_dir) / "offers.csv"
        baseline = generate_offer_baseline(catalog_path, db_path, offer_path)
        with offer_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))

    summary_rows = summarize_rows(rows, int(baseline["catalog_products"]))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_COLUMNS, lineterminator="\\n")
        writer.writeheader()
        writer.writerows(summary_rows)

    return {
        "catalog_products": int(baseline["catalog_products"]),
        "stores": len(SUPPORTED_STORES),
        "offers": len(rows),
        "output": str(output_path),
    }
