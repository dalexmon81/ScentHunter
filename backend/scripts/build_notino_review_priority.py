"""Build a conservative, prioritized Notino-to-catalog human review queue.

Inputs are a core-fragrance feed CSV and the candidate CSV emitted by
build_notino_match_candidates.py. This utility never approves a match and never
writes to the canonical catalog or offer database.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


AMBIGUITY_MARGIN_THRESHOLD = 0.05

PRIORITY = {
    "0_HOLD_INVALID_GTIN": 1,
    "0_HOLD_DUPLICATE_GTIN": 2,
    "0_HOLD_VARIANT_FORMAT": 3,
    "A_AMBIGUOUS_CANDIDATES": 4,
    "B_HIGH_CONFIDENCE_MANUAL_REVIEW": 5,
    "C_MEDIUM_CONFIDENCE_MANUAL_REVIEW": 6,
    "D_CONFLICT_OR_ATTRIBUTE_MISMATCH": 7,
    "E_LOW_CONFIDENCE_MANUAL_REVIEW": 8,
    "F_PRODUCT_ONLY_REQUIRES_NEW_VARIANT": 9,
    "G_NO_CANDIDATE": 10,
}

INSTRUCTIONS = {
    "0_HOLD_INVALID_GTIN": "Hold: GTIN check digit is invalid. Do not map or publish until corrected by the source.",
    "0_HOLD_DUPLICATE_GTIN": "Hold: this GTIN occurs on multiple feed external IDs. Resolve duplicate identity before mapping.",
    "0_HOLD_VARIANT_FORMAT": "Hold: feed listing is an explicit refill/recharge format. Do not map it to a standard bottle variant; verify or create the matching refill variant.",
    "A_AMBIGUOUS_CANDIDATES": "Ambiguous: the runner-up is a different canonical identity and is within 0.05 score points. Compare both before mapping.",
    "B_HIGH_CONFIDENCE_MANUAL_REVIEW": "Strong title, exact size and concentration candidate with a clear score lead. Verify identity and GTIN before approval.",
    "C_MEDIUM_CONFIDENCE_MANUAL_REVIEW": "Promising candidate; compare title, size, concentration and competing candidates.",
    "D_CONFLICT_OR_ATTRIBUTE_MISMATCH": "Attribute conflict; do not map automatically. Inspect gender, size, concentration and product format (refill/recharge/tester).",
    "E_LOW_CONFIDENCE_MANUAL_REVIEW": "Weak variant evidence; manual catalog research required.",
    "F_PRODUCT_ONLY_REQUIRES_NEW_VARIANT": "Product identity candidate only; current catalog has no purchasable variant match.",
    "G_NO_CANDIDATE": "No safe candidate in the current canonical catalog.",
}


def _truth(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_review_queue(feed_path: str | Path, candidates_path: str | Path) -> tuple[list[dict], dict]:
    with Path(feed_path).open(encoding="utf-8-sig", newline="") as handle:
        feed_rows = list(csv.DictReader(handle))
    with Path(candidates_path).open(encoding="utf-8-sig", newline="") as handle:
        candidate_rows = list(csv.DictReader(handle))

    if not feed_rows:
        raise ValueError("The core-fragrance feed CSV contains no rows.")
    if not candidate_rows:
        raise ValueError("The candidate CSV contains no rows.")

    candidates_by_id: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidate_rows:
        external_id = str(candidate.get("feed_external_id") or "").strip()
        if external_id:
            candidates_by_id[external_id].append(candidate)

    gtin_counts = Counter(str(row.get("gtin") or "").strip() for row in feed_rows)
    queue: list[dict] = []
    exact_gtin_ids: set[str] = set()
    candidate_ids: set[str] = set()

    for feed in feed_rows:
        external_id = str(feed.get("id") or "").strip()
        if not external_id:
            raise ValueError("A core-fragrance feed row is missing its external id.")
        ranked = sorted(
            candidates_by_id.get(external_id, []),
            key=lambda row: (
                _number(row.get("candidate_score")),
                _number(row.get("name_similarity")),
            ),
            reverse=True,
        )
        best = ranked[0] if ranked else {}
        runner = ranked[1] if len(ranked) > 1 else {}
        if best and best.get("review_status") == "needs_human_review":
            candidate_ids.add(external_id)
        if any(_truth(row.get("gtin_match")) for row in ranked):
            exact_gtin_ids.add(external_id)

        gtin = str(feed.get("gtin") or "").strip()
        gtin_valid = _truth(feed.get("gtin_valid"))
        title_folded = str(feed.get("title") or "").casefold()
        # Explicit refill/recharge listings are separate sellable formats.
        # "rechargeable" describes a refillable bottle, not necessarily a refill SKU.
        refill_format = bool(re.search(r"\\b(?:refill|recharge)\\b", title_folded)) and not bool(re.search(r"\\bfull\\s+recharge\\b", title_folded))
        duplicate_count = gtin_counts.get(gtin, 0) if gtin else 0
        best_score = _number(best.get("candidate_score"))
        runner_score = _number(runner.get("candidate_score"))
        different_runner_identity = bool(runner) and (
            str(best.get("canonical_variant_id") or "") != str(runner.get("canonical_variant_id") or "")
            or str(best.get("canonical_product_id") or "") != str(runner.get("canonical_product_id") or "")
        )
        ambiguous = (
            different_runner_identity
            and (best_score - runner_score) < AMBIGUITY_MARGIN_THRESHOLD
        )

        if not gtin_valid:
            gtin_status = "hold_invalid_checksum"
            priority = "0_HOLD_INVALID_GTIN"
        elif duplicate_count > 1:
            gtin_status = "hold_duplicate_in_feed"
            priority = "0_HOLD_DUPLICATE_GTIN"
        else:
            gtin_status = "valid_unique_checksum"
            scope = str(best.get("candidate_scope") or "")
            band = str(best.get("confidence_band") or "")
            gender_conflict = _truth(best.get("gender_conflict"))
            if refill_format and scope == "variant":
                priority = "0_HOLD_VARIANT_FORMAT"
            elif ambiguous:
                priority = "A_AMBIGUOUS_CANDIDATES"
            elif not best or str(best.get("review_status") or "") == "no_candidate":
                priority = "G_NO_CANDIDATE"
            elif scope == "product_only":
                priority = "F_PRODUCT_ONLY_REQUIRES_NEW_VARIANT"
            elif scope == "variant" and (band == "low" or gender_conflict or refill_format):
                priority = "D_CONFLICT_OR_ATTRIBUTE_MISMATCH"
            elif scope == "variant" and band == "review_high":
                priority = "B_HIGH_CONFIDENCE_MANUAL_REVIEW"
            elif scope == "variant" and band == "review_medium":
                priority = "C_MEDIUM_CONFIDENCE_MANUAL_REVIEW"
            else:
                priority = "E_LOW_CONFIDENCE_MANUAL_REVIEW"

        row = dict(feed)
        row.update({
            "gtin_review_status": gtin_status,
            "gtin_duplicate_count": duplicate_count,
            "priority": priority,
            "review_instruction": INSTRUCTIONS[priority],
            "candidate_score": best.get("candidate_score", "0"),
            "confidence_band": best.get("confidence_band", "no_candidate"),
            "canonical_product_id": best.get("canonical_product_id", ""),
            "canonical_variant_id": best.get("canonical_variant_id", ""),
            "candidate_scope": best.get("candidate_scope", ""),
            "canonical_brand": best.get("canonical_brand", ""),
            "canonical_names": best.get("canonical_names", ""),
            "canonical_size_ml": best.get("canonical_size_ml", ""),
            "canonical_concentration": best.get("canonical_concentration", ""),
            "name_similarity": best.get("name_similarity", "0"),
            "size_match": best.get("size_match", "False"),
            "concentration_match": best.get("concentration_match", "False"),
            "gender_conflict": best.get("gender_conflict", "False"),
            "variant_format_conflict": refill_format,
            "runner_up_score": runner.get("candidate_score", ""),
            "runner_up_product_id": runner.get("canonical_product_id", ""),
            "runner_up_variant_id": runner.get("canonical_variant_id", ""),
            "score_margin": round(best_score - runner_score, 4),
            "ambiguous": ambiguous,
            "_priority_order": PRIORITY[priority],
        })
        queue.append(row)

    queue.sort(
        key=lambda row: (
            row["_priority_order"],
            -_number(row.get("candidate_score")),
            -_number(row.get("score_margin")),
            str(row.get("id") or ""),
        )
    )
    for row in queue:
        row.pop("_priority_order", None)

    counts = Counter(row["priority"] for row in queue)
    summary = {
        "core_fragrance_products": len(feed_rows),
        "candidate_csv_rows": len(candidate_rows),
        "products_with_any_candidate": len(candidate_ids),
        "products_without_candidate": len(feed_rows) - len(candidate_ids),
        "exact_gtin_matches_to_catalog": len(exact_gtin_ids),
        "invalid_gtin_hold_rows": counts["0_HOLD_INVALID_GTIN"],
        "duplicate_gtin_hold_rows": counts["0_HOLD_DUPLICATE_GTIN"],
        "ambiguous_candidate_rows": counts["A_AMBIGUOUS_CANDIDATES"],
        "ambiguity_margin_threshold": AMBIGUITY_MARGIN_THRESHOLD,
        "priority_counts": dict(counts),
        "automatic_matches_approved": 0,
        "catalog_writes": 0,
        "production_imports": 0,
        "policy": "Every candidate remains human-review-only; invalid and duplicated GTINs are held.",
    }
    return queue, summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("feed", type=Path, help="Core-fragrance feed CSV")
    parser.add_argument("candidates", type=Path, help="Candidate CSV from build_notino_match_candidates.py")
    parser.add_argument("--csv", type=Path, default=Path("notino-catalog-review-priority.csv"))
    parser.add_argument("--json", type=Path, default=Path("notino-catalog-review-priority.json"))
    args = parser.parse_args()

    rows, summary = build_review_queue(args.feed, args.candidates)
    fields = list(rows[0]) if rows else []
    with args.csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary["csv"] = str(args.csv)
    args.json.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
