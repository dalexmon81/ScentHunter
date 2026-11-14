"""Export the strongest Notino candidates into a compact human-review CSV.

This is a convenience view over the prioritized queue, not an approval step.
Every exported row remains pending human verification; no catalog or database
writes are performed.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

REQUIRED_PRIORITY = "B_HIGH_CONFIDENCE_MANUAL_REVIEW"
OUTPUT_FIELDS = [
    "id", "title", "brand", "gtin", "price", "sale_price", "availability",
    "size", "product_type", "gender", "link", "last_updated",
    "canonical_product_id", "canonical_variant_id", "canonical_brand",
    "canonical_names", "canonical_size_ml", "canonical_concentration",
    "candidate_score", "name_similarity", "size_match",
    "concentration_match", "gender_conflict", "variant_format_conflict",
    "review_instruction",
]


def export_review_rows(source: str | Path) -> tuple[list[dict[str, str]], dict]:
    with Path(source).open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    selected = []
    for row in rows:
        if row.get("priority") != REQUIRED_PRIORITY:
            continue
        # Defensive guard: only fully specified variant candidates enter this
        # focused queue. The output still requires a human to approve identity.
        if not row.get("canonical_product_id") or not row.get("canonical_variant_id"):
            continue
        if str(row.get("gender_conflict", "")).casefold() == "true":
            continue
        if str(row.get("variant_format_conflict", "")).casefold() == "true":
            continue
        selected.append({field: row.get(field, "") for field in OUTPUT_FIELDS})
    summary = {
        "source_rows": len(rows),
        "manual_review_rows": len(selected),
        "priority": REQUIRED_PRIORITY,
        "automatic_approvals": 0,
        "catalog_writes": 0,
        "policy": "Human verification required for every row; this export does not approve or import matches.",
    }
    return selected, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Prioritized Notino review queue CSV")
    parser.add_argument("--csv", type=Path, default=Path("notino-high-confidence-review.csv"))
    parser.add_argument("--json", type=Path, default=Path("notino-high-confidence-review-summary.json"))
    args = parser.parse_args()

    rows, summary = export_review_rows(args.source)
    with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    summary["csv"] = str(args.csv)
    args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
