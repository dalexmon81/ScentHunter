"""Build a read-only Notino catalog-expansion review queue.

Only feed rows whose normalized brand is absent from the canonical catalog are
included. Valid unique GTINs are eligible for manual identity review, never
automatic catalog insertion. Invalid and colliding GTINs are explicitly held.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path

from backend.gtin import is_valid_gtin
from backend.scripts.build_notino_match_candidates import (
    _brand_key,
    extract_concentration,
    extract_gender,
    iter_perfume_rows,
    parse_size,
    strip_product_noise,
)


def build_expansion_proposals(feed_path: str | Path, catalog_path: str | Path) -> tuple[list[dict], dict]:
    catalog = json.loads(Path(catalog_path).read_text(encoding="utf-8"))
    known_brand_keys = {
        _brand_key(str(product.get("brand_name") or ""))
        for product in catalog.get("products", [])
        if str(product.get("brand_name") or "").strip()
    }
    feed_rows = list(iter_perfume_rows(feed_path))
    gtin_counts = Counter(str(row.get("gtin") or "").strip() for row in feed_rows)
    proposals = []

    for row in feed_rows:
        brand = str(row.get("brand") or "").strip()
        if not brand or _brand_key(brand) in known_brand_keys:
            continue

        gtin = str(row.get("gtin") or "").strip()
        valid_gtin = is_valid_gtin(gtin)
        collision_count = gtin_counts.get(gtin, 0) if gtin else 0
        if not valid_gtin:
            review_status = "hold_invalid_gtin"
        elif collision_count > 1:
            review_status = "hold_duplicate_gtin"
        else:
            review_status = "ready_for_manual_identity_review"

        title = str(row.get("title") or "").strip()
        proposals.append({
            "review_status": review_status,
            "catalog_write_allowed": False,
            "feed_external_id": row.get("id", ""),
            "feed_brand": brand,
            "normalized_brand_key": _brand_key(brand),
            "feed_title": title,
            "name_review_candidate": strip_product_noise(title),
            "product_type": row.get("product_type", ""),
            "concentration_candidate": extract_concentration(title) or "",
            "size_ml_candidate": parse_size(row.get("size", "")) or parse_size(title) or "",
            "gender_candidate": extract_gender(title) or "",
            "gtin": gtin,
            "gtin_valid": valid_gtin,
            "same_gtin_feed_row_count": collision_count,
            "price": row.get("price", ""),
            "sale_price": row.get("sale_price", ""),
            "currency": row.get("currency", ""),
            "availability": row.get("availability", ""),
            "affiliate_url": row.get("link", ""),
            "last_updated": row.get("last_updated", ""),
        })

    status_counts = Counter(row["review_status"] for row in proposals)
    summary = {
        "core_feed_rows": len(feed_rows),
        "canonical_products": len(catalog.get("products", [])),
        "feed_brands_absent_from_catalog": len({row["normalized_brand_key"] for row in proposals}),
        "proposal_rows": len(proposals),
        "unique_gtin_manual_review_rows": status_counts["ready_for_manual_identity_review"],
        "invalid_gtin_hold_rows": status_counts["hold_invalid_gtin"],
        "duplicate_gtin_hold_rows": status_counts["hold_duplicate_gtin"],
        "automatic_catalog_insertions": 0,
        "database_writes": 0,
        "policy": "No proposed row is approved for catalog insertion; manual identity review is mandatory.",
    }
    return proposals, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path)
    parser.add_argument("catalog", type=Path)
    parser.add_argument("--csv", type=Path, default=Path("notino-catalog-expansion-review.csv"))
    parser.add_argument("--json", type=Path, default=Path("notino-catalog-expansion-review.json"))
    args = parser.parse_args()

    proposals, summary = build_expansion_proposals(args.feed, args.catalog)
    fields = list(proposals[0]) if proposals else [
        "review_status", "catalog_write_allowed", "feed_external_id", "feed_brand",
        "normalized_brand_key", "feed_title", "name_review_candidate", "product_type",
        "concentration_candidate", "size_ml_candidate", "gender_candidate", "gtin",
        "gtin_valid", "same_gtin_feed_row_count", "price", "sale_price", "currency",
        "availability", "affiliate_url", "last_updated",
    ]
    with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(proposals)
    summary["csv"] = str(args.csv)
    args.json.write_text(
        json.dumps({"summary": summary, "proposals": proposals}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
