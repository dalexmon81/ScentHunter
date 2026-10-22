"""Read-only shadow comparison of legacy and next matchers on real catalog identities.

This is a diagnostic sample, not a production traffic replay: offers are generated
from canonical catalog entries so both matchers receive the same known identities.
The JSON report is written only to the CI workspace and uploaded as an artifact.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from backend.product_matcher import ProductMatcher
from backend.scenthunter_next_engine.next_engine_service import NextEngineService


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "backend" / "product_catalog.json"
FAMILY_PATH = ROOT / "backend" / "family_registry.json"
REPORT_PATH = ROOT / "next-engine-shadow-comparison.json"
SAMPLE_LIMIT = 80


def _key(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _identity_key(brand: object, name: object) -> str:
    return f"{_key(brand)}::{_key(name)}"


def test_generate_read_only_legacy_vs_next_shadow_report():
    catalog_before = CATALOG_PATH.read_bytes()
    service = NextEngineService.from_catalog_file(CATALOG_PATH)
    legacy_catalog = json.loads(catalog_before.decode("utf-8"))
    family_registry = json.loads(FAMILY_PATH.read_text(encoding="utf-8"))
    legacy = ProductMatcher(legacy_catalog, family_registry)

    candidates = []
    seen_products = set()
    for product in service.catalog.all_products():
        if product.product_id in seen_products:
            continue
        sized = [variant for variant in product.variants if variant.size_ml is not None]
        if not sized:
            continue
        candidates.append((product, sized[0]))
        seen_products.add(product.product_id)
        if len(candidates) >= SAMPLE_LIMIT:
            break

    assert candidates, "No sized canonical catalog variants available for comparison"

    records = [
        {
            "name": product.name,
            "brand": product.brand,
            "size_ml": variant.size_ml,
            "price": "19.95",
            "currency": "EUR",
            "url": f"https://shadow-comparison.invalid/{index}",
            "store": "shadow-comparison",
        }
        for index, (product, variant) in enumerate(candidates)
    ]
    next_result = service.process_records(records, retailer="shadow-comparison")
    next_by_name = {}
    for group in next_result.groups:
        for offer in group.offers:
            next_by_name[_identity_key(offer.brand_raw, offer.raw_name)] = {
                "status": "matched",
                "product_id": group.canonical_product_id,
                "variant_id": group.canonical_variant_id,
            }
    for item in next_result.unresolved:
        next_by_name[_identity_key(item.offer.brand_raw, item.offer.raw_name)] = {
            "status": "unresolved",
            "reason": item.reason,
        }
    for item in next_result.ambiguous:
        next_by_name[_identity_key(item.offer.brand_raw, item.offer.raw_name)] = {
            "status": "ambiguous",
            "candidate_product_ids": list(item.candidate_product_ids),
        }

    status_counts = Counter()
    comparisons = []
    for index, ((product, variant), record) in enumerate(zip(candidates, records)):
        try:
            old = legacy.match(record, query=f"{product.brand} {product.name}")
            if old is None:
                old_summary = {"status": "unmatched"}
            else:
                old_summary = {
                    "status": "matched",
                    "canonical_name": old.get("canonical_name") or old.get("name") or product.name,
                    "product_identity": old.get("product_identity") or old.get("catalog_id"),
                    "variant_id": old.get("variant_id"),
                    "size_ml": old.get("size_ml"),
                    "match_method": old.get("match_method"),
                }
        except Exception as exc:
            old_summary = {"status": "error", "error_type": type(exc).__name__}

        new_summary = next_by_name.get(_identity_key(product.brand, product.name), {"status": "missing_result"})
        status_counts[f"legacy_{old_summary['status']}"] += 1
        status_counts[f"next_{new_summary['status']}"] += 1

        legacy_name = _key(old_summary.get("canonical_name"))
        next_name = _key(product.name) if new_summary["status"] == "matched" else ""
        comparisons.append({
            "sample": index,
            "expected_canonical_name": product.name,
            "expected_brand": product.brand,
            "expected_size_ml": variant.size_ml,
            "legacy": old_summary,
            "next": new_summary,
            "legacy_name_agrees_with_expected": bool(legacy_name and next_name and legacy_name == next_name),
            "legacy_size_agrees_with_expected": (
                old_summary.get("size_ml") is not None
                and float(old_summary["size_ml"]) == float(variant.size_ml)
            ),
            "next_identity_agrees_with_expected": (
                new_summary.get("product_id") == product.product_id
                and new_summary.get("variant_id") == variant.variant_id
            ),
        })

    report = {
        "mode": "read-only synthetic canonical-identity shadow comparison",
        "production_traffic_replayed": False,
        "catalog_modified": False,
        "database_accessed": False,
        "sample_limit": SAMPLE_LIMIT,
        "sample_count": len(comparisons),
        "status_counts": dict(sorted(status_counts.items())),
        "legacy_expected_name_agreements": sum(x["legacy_name_agrees_with_expected"] for x in comparisons),
        "legacy_expected_size_agreements": sum(x["legacy_size_agrees_with_expected"] for x in comparisons),
        "next_expected_identity_agreements": sum(x["next_identity_agrees_with_expected"] for x in comparisons),
        "comparisons": comparisons,
        "interpretation": (
            "Synthetic canonical-name offers test identity round-tripping only. "
            "This is not evidence of parity on live retailer payloads or production traffic."
        ),
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert CATALOG_PATH.read_bytes() == catalog_before, "Read-only comparison modified the catalog"
    assert report["sample_count"] > 0
