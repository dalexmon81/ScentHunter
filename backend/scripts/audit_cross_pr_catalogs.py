"""Read-only cross-PR catalog collision audit.

The workflow fetches all remote branches, then this script compares selected
open catalog PR snapshots against one shared baseline. It reports only records
introduced relative to that baseline and detects collisions between branches.
It never edits catalog data.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import unicodedata
from collections import defaultdict
from typing import Any

BASE_REF = "catalog/requested-brand-harvest-2026-11-08"
CANDIDATE_REFS = (
    "catalog/velixir-28-fragrance-variant-reconciliation-2026-11-08",  # PR 465
    "catalog/velixir-official-product-variants-2026-11-08",  # PR 517
    "catalog/mykonos-detail-evidence-2026-11-08",  # PR 539
    "catalog/cumulative-source-reconciled-2026-11-08",  # PR 546
    "catalog/gulf-orchid-source-reconciliation-2026-11-08",  # PR 542
    "catalog/gulf-orchid-official-new-arrivals-2026-11-08",  # PR 554
    "catalog/lattafa-official-new-launches-2026-11-08",  # PR 555, cumulative
    "catalog/armaf-official-detail-audit-2026-11-08",  # PR 558
    "catalog/lattafa-four-official-products-2026-11-08",  # PR 562
    "catalog/armaf-eu-official-2026-11-08",  # PR 564
    "catalog/armaf-official-fragrance-additions-2026-11-08",  # PR 565, cumulative
    "catalog/armaf-variant-concentration-verified-2026-11-08",  # PR 569
    "catalog/mykonos-travel-variant-concentration-verified-2026-11-08",  # PR 570
    "catalog/french-avenue-aromatix-variant-concentration-verified-2026-11-08",  # PR 571
    "catalog/assaf-gris-erik-100ml-variant-concentration-2026-11-08",  # PR 572
    "catalog/armaf-concentration-verification-2026-11-08",  # PR 573
    "catalog/khadlaj-hareem-al-sultan-gold-oil-source-verified-2026-11-08",  # PR 574
    "catalog/verified-incense-fragrances-2026-11-08",  # PR 575
    "catalog/lattafa-official-launches-2026-11-08",  # PR 576, cumulative
    "catalog/lattafa-amethyst-petra-2026-11-08",  # PR 577, cumulative
    "catalog/lattafa-asad-polar-2026-11-08",  # PR 578, cumulative
    "catalog/paris-corner-official-pages-2026-11-08",  # PR 579, cumulative
)

CATALOG_PATH = "backend/product_catalog.json"


def normalize(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", text.casefold())


def git_json(ref: str, path: str) -> dict[str, Any]:
    spec = f"refs/remotes/origin/{ref}:{path}"
    result = subprocess.run(
        ["git", "show", spec],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    parsed = json.loads(result.stdout)
    if not isinstance(parsed, dict):
        raise ValueError(f"{spec} must contain a JSON object")
    return parsed


def product_identity(row: dict[str, Any]) -> tuple[str, str]:
    brand = row.get("brand_name") or row.get("brand")
    name = row.get("canonical_name") or row.get("name")
    return normalize(brand), normalize(name)


def variant_identity(row: dict[str, Any]) -> tuple[str, Any, str]:
    return (
        str(row.get("product_id") or ""),
        row.get("size_ml"),
        normalize(row.get("concentration")),
    )


def index_baseline(catalog: dict[str, Any]) -> tuple[set, set, set, set]:
    products = catalog.get("products", [])
    variants = catalog.get("variants", [])
    product_ids = {str(row.get("product_id") or "") for row in products}
    product_keys = {product_identity(row) for row in products}
    variant_ids = {str(row.get("variant_id") or "") for row in variants}
    variant_keys = {variant_identity(row) for row in variants}
    return product_ids, product_keys, variant_ids, variant_keys


def audit() -> int:
    baseline = git_json(BASE_REF, CATALOG_PATH)
    base_product_ids, base_product_keys, base_variant_ids, base_variant_keys = (
        index_baseline(baseline)
    )

    products_by_identity: dict[tuple[str, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    variants_by_tuple: dict[tuple[str, Any, str], dict[str, set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    product_id_to_identity: dict[str, dict[tuple[str, str], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )
    variant_id_to_tuple: dict[str, dict[tuple[str, Any, str], set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    loaded = 0
    for ref in CANDIDATE_REFS:
        catalog = git_json(ref, CATALOG_PATH)
        loaded += 1
        for row in catalog.get("products", []):
            product_id = str(row.get("product_id") or "")
            identity = product_identity(row)
            if not product_id or not all(identity):
                continue
            if product_id in base_product_ids and identity in base_product_keys:
                continue
            products_by_identity[identity][product_id].add(ref)
            product_id_to_identity[product_id][identity].add(ref)

        for row in catalog.get("variants", []):
            variant_id = str(row.get("variant_id") or "")
            key = variant_identity(row)
            if not variant_id or not key[0] or key[1] is None:
                continue
            if variant_id in base_variant_ids and key in base_variant_keys:
                continue
            variants_by_tuple[key][variant_id].add(ref)
            variant_id_to_tuple[variant_id][key].add(ref)

    findings: list[str] = []
    for identity, ids_to_refs in sorted(products_by_identity.items()):
        if len(ids_to_refs) > 1:
            refs = sorted({ref for refs in ids_to_refs.values() for ref in refs})
            ids = sorted(ids_to_refs)
            findings.append(
                f"PRODUCT IDENTITY COLLISION {identity}: product_ids={ids}; branches={refs}"
            )

    for product_id, identities_to_refs in sorted(product_id_to_identity.items()):
        if len(identities_to_refs) > 1:
            refs = sorted({ref for refs in identities_to_refs.values() for ref in refs})
            findings.append(
                f"PRODUCT ID REUSED {product_id}: identities={list(identities_to_refs)}; branches={refs}"
            )

    for key, ids_to_refs in sorted(variants_by_tuple.items(), key=lambda item: str(item[0])):
        if len(ids_to_refs) > 1:
            refs = sorted({ref for refs in ids_to_refs.values() for ref in refs})
            ids = sorted(ids_to_refs)
            findings.append(
                f"VARIANT TUPLE COLLISION {key}: variant_ids={ids}; branches={refs}"
            )

    for variant_id, tuples_to_refs in sorted(variant_id_to_tuple.items()):
        if len(tuples_to_refs) > 1:
            refs = sorted({ref for refs in tuples_to_refs.values() for ref in refs})
            findings.append(
                f"VARIANT ID REUSED {variant_id}: tuples={list(tuples_to_refs)}; branches={refs}"
            )

    print(f"Cross-PR catalog audit: baseline={BASE_REF}; candidate_branches={loaded}")
    print(
        "Baseline sizes: "
        f"products={len(baseline.get('products', []))}, "
        f"variants={len(baseline.get('variants', []))}"
    )
    if findings:
        print(f"BLOCKED: {len(findings)} cross-branch collision(s) detected.")
        for finding in findings:
            print(f" - {finding}")
        return 1

    print("PASS: no cross-branch product or variant identity collisions detected.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(audit())
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ERROR: cross-PR audit could not load its required inputs: {exc}", file=sys.stderr)
        raise SystemExit(2)
