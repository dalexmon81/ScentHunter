"""Read-only audit of direct additions across selected open catalog PRs.

Each PR is compared with its actual GitHub base branch. This avoids treating
records inherited from a parent/cumulative PR as fresh additions. Direct
additions are then compared across PRs and against the shared catalog baseline.
The script reports blockers only; it never edits catalog data.
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
CATALOG_PATH = "backend/product_catalog.json"
FAMILY_REGISTRY_PATH = "backend/family_registry.json"

# (PR number, head branch, actual PR base branch)
CANDIDATE_PRS = (
    (465, "catalog/velixir-28-fragrance-variant-reconciliation-2026-11-08", "catalog/mykonos-fragrantica-84-reconciliation-2026-11-08"),
    (517, "catalog/velixir-official-product-variants-2026-11-08", "catalog/paris-corner-ministry-of-oud-official-harvest-2026-11-08"),
    (539, "catalog/mykonos-detail-evidence-2026-11-08", BASE_REF),
    (546, "catalog/cumulative-source-reconciled-2026-11-08", "catalog/cumulative-requested-brands-2026-11-08"),
    (542, "catalog/gulf-orchid-source-reconciliation-2026-11-08", BASE_REF),
    (554, "catalog/gulf-orchid-official-new-arrivals-2026-11-08", BASE_REF),
    (555, "catalog/lattafa-official-new-launches-2026-11-08", "catalog/gulf-orchid-official-new-arrivals-2026-11-08"),
    (558, "catalog/armaf-official-detail-audit-2026-11-08", "catalog/armaf-official-new-exclusive-2026-11-08"),
    (562, "catalog/lattafa-four-official-products-2026-11-08", "catalog/lattafa-mishlah-official-page-2026-11-08"),
    (564, "catalog/armaf-eu-official-2026-11-08", "catalog/maison-alhambra-eu-official-2026-11-08"),
    (565, "catalog/armaf-official-fragrance-additions-2026-11-08", "catalog/lattafa-four-official-products-2026-11-08"),
    (569, "catalog/armaf-variant-concentration-verified-2026-11-08", BASE_REF),
    (570, "catalog/mykonos-travel-variant-concentration-verified-2026-11-08", BASE_REF),
    (571, "catalog/french-avenue-aromatix-variant-concentration-verified-2026-11-08", BASE_REF),
    (572, "catalog/assaf-gris-erik-100ml-variant-concentration-2026-11-08", BASE_REF),
    (573, "catalog/armaf-concentration-verification-2026-11-08", BASE_REF),
    (574, "catalog/khadlaj-hareem-al-sultan-gold-oil-source-verified-2026-11-08", BASE_REF),
    (575, "catalog/verified-incense-fragrances-2026-11-08", BASE_REF),
    (576, "catalog/lattafa-official-launches-2026-11-08", "catalog/verified-incense-fragrances-2026-11-08"),
    (577, "catalog/lattafa-amethyst-petra-2026-11-08", "catalog/lattafa-official-launches-2026-11-08"),
    (578, "catalog/lattafa-asad-polar-2026-11-08", "catalog/lattafa-amethyst-petra-2026-11-08"),
    (579, "catalog/paris-corner-official-pages-2026-11-08", "catalog/lattafa-asad-polar-2026-11-08"),
)


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
    return (
        normalize(row.get("brand_name") or row.get("brand")),
        normalize(row.get("canonical_name") or row.get("name")),
    )


def variant_identity(row: dict[str, Any]) -> tuple[str, Any, str]:
    return (
        str(row.get("product_id") or ""),
        row.get("size_ml"),
        normalize(row.get("concentration")),
    )


def product_pairs(catalog: dict[str, Any]) -> set[tuple[str, tuple[str, str]]]:
    return {
        (str(row.get("product_id") or ""), product_identity(row))
        for row in catalog.get("products", [])
        if row.get("product_id") and all(product_identity(row))
    }


def variant_pairs(catalog: dict[str, Any]) -> set[tuple[str, tuple[str, Any, str]]]:
    return {
        (str(row.get("variant_id") or ""), variant_identity(row))
        for row in catalog.get("variants", [])
        if row.get("variant_id") and row.get("product_id") and row.get("size_ml") is not None
    }


def registry_entries(registry: dict[str, Any]) -> set[tuple[str, str]]:
    entries: set[tuple[str, str]] = set()
    for family in registry.get("families", []):
        family_id = str(family.get("family_id") or "")
        if not family_id:
            continue
        for product in family.get("products", []):
            name = normalize(product.get("canonical_name"))
            if name:
                entries.add((family_id, name))
    return entries


def add_product(pair, source, by_identity, by_id, pair_sources):
    product_id, identity = pair
    by_identity[identity][product_id].add(source)
    by_id[product_id][identity].add(source)
    pair_sources[pair].add(source)


def add_variant(pair, source, by_tuple, by_id, pair_sources):
    variant_id, key = pair
    by_tuple[key][variant_id].add(source)
    # A concentration correction on an existing variant ID is allowed.
    # Reusing that ID for a different product or bottle size is not.
    by_id[variant_id][(key[0], key[1])].add(source)
    pair_sources[pair].add(source)


def audit() -> int:
    baseline = git_json(BASE_REF, CATALOG_PATH)
    baseline_registry = git_json(BASE_REF, FAMILY_REGISTRY_PATH)
    base_products = product_pairs(baseline)
    base_variants = variant_pairs(baseline)
    base_registry = registry_entries(baseline_registry)

    products_by_identity = defaultdict(lambda: defaultdict(set))
    products_by_id = defaultdict(lambda: defaultdict(set))
    variants_by_tuple = defaultdict(lambda: defaultdict(set))
    variants_by_id = defaultdict(lambda: defaultdict(set))
    product_addition_sources = defaultdict(set)
    variant_addition_sources = defaultdict(set)
    registry_addition_sources = defaultdict(set)

    # Baseline records are context for identity/ID collisions, but are not
    # considered duplicate additions shared by multiple PRs.
    for pair in base_products:
        add_product(pair, "BASELINE", products_by_identity, products_by_id, defaultdict(set))
    for pair in base_variants:
        add_variant(pair, "BASELINE", variants_by_tuple, variants_by_id, defaultdict(set))

    loaded = 0
    for pr_number, head_ref, base_ref in CANDIDATE_PRS:
        head_catalog = git_json(head_ref, CATALOG_PATH)
        base_catalog = git_json(base_ref, CATALOG_PATH)
        head_registry = git_json(head_ref, FAMILY_REGISTRY_PATH)
        base_registry_for_pr = git_json(base_ref, FAMILY_REGISTRY_PATH)
        source = f"PR #{pr_number} ({head_ref})"
        loaded += 1

        new_products = product_pairs(head_catalog) - product_pairs(base_catalog)
        new_variants = variant_pairs(head_catalog) - variant_pairs(base_catalog)
        new_registry = registry_entries(head_registry) - registry_entries(base_registry_for_pr)

        for pair in new_products:
            add_product(pair, source, products_by_identity, products_by_id, product_addition_sources)
        for pair in new_variants:
            add_variant(pair, source, variants_by_tuple, variants_by_id, variant_addition_sources)
        for entry in new_registry - base_registry:
            registry_addition_sources[entry].add(source)

    findings: list[str] = []
    for identity, ids_to_sources in sorted(products_by_identity.items()):
        if len(ids_to_sources) > 1:
            sources = sorted({src for values in ids_to_sources.values() for src in values})
            findings.append(
                f"PRODUCT IDENTITY COLLISION {identity}: product_ids={sorted(ids_to_sources)}; sources={sources}"
            )

    for product_id, identities_to_sources in sorted(products_by_id.items()):
        if len(identities_to_sources) > 1:
            sources = sorted({src for values in identities_to_sources.values() for src in values})
            findings.append(
                f"PRODUCT ID REUSED {product_id}: identities={list(identities_to_sources)}; sources={sources}"
            )

    for key, ids_to_sources in sorted(variants_by_tuple.items(), key=lambda item: str(item[0])):
        if len(ids_to_sources) > 1:
            sources = sorted({src for values in ids_to_sources.values() for src in values})
            findings.append(
                f"VARIANT TUPLE COLLISION {key}: variant_ids={sorted(ids_to_sources)}; sources={sources}"
            )

    for variant_id, product_sizes in sorted(variants_by_id.items()):
        if len(product_sizes) > 1:
            sources = sorted({src for values in product_sizes.values() for src in values})
            findings.append(
                f"VARIANT ID REUSED FOR DIFFERENT PRODUCT/SIZE {variant_id}: keys={list(product_sizes)}; sources={sources}"
            )

    for pair, sources_set in sorted(product_addition_sources.items(), key=lambda item: str(item[0])):
        if len(sources_set) > 1:
            findings.append(
                f"IDENTICAL PRODUCT ADDITION SHARED {pair}: sources={sorted(sources_set)}"
            )

    for pair, sources_set in sorted(variant_addition_sources.items(), key=lambda item: str(item[0])):
        if len(sources_set) > 1:
            findings.append(
                f"IDENTICAL VARIANT ADDITION SHARED {pair}: sources={sorted(sources_set)}"
            )

    for entry, sources_set in sorted(registry_addition_sources.items()):
        if len(sources_set) > 1:
            findings.append(
                f"FAMILY REGISTRY ENTRY SHARED {entry}: sources={sorted(sources_set)}"
            )

    print(
        f"Cross-PR catalog audit: baseline={BASE_REF}; "
        f"candidate_prs={loaded}; direct_changes_only=true"
    )
    print(
        "Baseline sizes: "
        f"products={len(baseline.get('products', []))}, "
        f"variants={len(baseline.get('variants', []))}, "
        f"families={len(baseline_registry.get('families', []))}"
    )
    if findings:
        print(f"BLOCKED: {len(findings)} cross-PR collision(s) detected.")
        for finding in findings:
            print(f" - {finding}")
        return 1

    print("PASS: no cross-PR product, variant or family-registry overlaps detected.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(audit())
    except (subprocess.CalledProcessError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"ERROR: cross-PR audit could not load its required inputs: {exc}", file=sys.stderr)
        raise SystemExit(2)
