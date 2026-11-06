"""Validate the operational Phase 0 retailer baseline CSV.

Exit non-zero until all nine in-scope retailers have at least one distinct,
valid offer row. Store status rows are informational and never count as offers.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

STORES = (
    "bplatz", "deloox", "easycosmetic", "notino", "orioudh",
    "parfumcity", "parfumzentrum", "perfumemarket", "sabina",
)
REQUIRED_COLUMNS = {
    "store", "canonical_product_id", "brand", "fragrance", "concentration",
    "size_ml", "gtin", "external_product_id", "offer_url", "price",
    "currency", "availability", "captured_at", "source", "match_status",
    "match_confidence", "is_valid_offer",
}
VALID_STOCK = {
    "in_stock", "out_of_stock", "preorder", "backorder",
    "limited_availability",
}
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")


def validate_baseline(path: str | Path) -> dict[str, Any]:
    errors: list[str] = []
    counts: Counter[str] = Counter()
    seen: set[tuple[str, str, str, str]] = set()
    rows_read = 0
    try:
        handle = Path(path).open("r", newline="", encoding="utf-8-sig")
    except OSError as exc:
        return {"passed": False, "errors": [f"cannot_open_csv: {exc}"],
                "offer_count": 0, "store_offer_counts": {s: 0 for s in STORES}}

    with handle:
        reader = csv.DictReader(handle)
        headers = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_COLUMNS - headers)
        if missing:
            errors.append("missing_columns: " + ", ".join(missing))
            return {"passed": False, "errors": errors, "offer_count": 0,
                    "store_offer_counts": {s: 0 for s in STORES}}

        for line, row in enumerate(reader, start=2):
            rows_read += 1
            store = (row.get("store") or "").strip().lower()
            if store not in STORES:
                errors.append(f"line_{line}: unexpected_store={store or '<empty>'}")
                continue

            # A status-only row has no source and is not an offer.
            if not (row.get("source") or "").strip():
                continue

            counts[store] += 1
            required_values = (
                "canonical_product_id", "brand", "fragrance", "concentration",
                "external_product_id", "offer_url", "price", "currency",
                "availability", "captured_at", "source", "match_status",
                "match_confidence", "is_valid_offer",
            )
            empty = [name for name in required_values if not (row.get(name) or "").strip()]
            if empty:
                errors.append(f"line_{line}: empty_fields={','.join(empty)}")

            url = (row.get("offer_url") or "").strip()
            if not url.startswith("https://"):
                errors.append(f"line_{line}: offer_url_must_be_https")

            currency = (row.get("currency") or "").strip()
            if not CURRENCY_RE.fullmatch(currency):
                errors.append(f"line_{line}: invalid_currency={currency or '<empty>'}")

            try:
                price = float(row.get("price") or "")
                if price <= 0:
                    raise ValueError
            except ValueError:
                errors.append(f"line_{line}: price_must_be_positive")

            if (row.get("availability") or "").strip().lower() not in VALID_STOCK:
                errors.append(f"line_{line}: invalid_availability")

            if (row.get("match_status") or "").strip().lower() != "matched":
                errors.append(f"line_{line}: offer_not_matched")

            if (row.get("is_valid_offer") or "").strip().lower() != "true":
                errors.append(f"line_{line}: offer_not_validated")

            try:
                confidence = float(row.get("match_confidence") or "")
                if not 0 <= confidence <= 1:
                    raise ValueError
            except ValueError:
                errors.append(f"line_{line}: invalid_match_confidence")

            key = (
                store,
                (row.get("external_product_id") or "").strip(),
                (row.get("canonical_product_id") or "").strip(),
                (row.get("size_ml") or "").strip(),
            )
            if key in seen:
                errors.append(f"line_{line}: duplicate_offer_key={key}")
            seen.add(key)

    unknown = sorted(set(counts) - set(STORES))
    missing_stores = [store for store in STORES if counts[store] == 0]
    if missing_stores:
        errors.append("stores_without_real_offers: " + ", ".join(missing_stores))
    return {
        "passed": not errors,
        "rows_read": rows_read,
        "offer_count": sum(counts.values()),
        "store_offer_counts": {store: counts[store] for store in STORES},
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args()
    report = validate_baseline(args.csv_path)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
