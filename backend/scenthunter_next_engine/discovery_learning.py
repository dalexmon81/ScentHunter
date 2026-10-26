"""Evidence-backed variant learning from repeated live retailer observations.

This module learns only missing variants of an already-existing canonical
product. It never creates product identities, merges products, infers sizes,
or promotes a one-retailer guess. Two independent retailer domains must agree
on the exact product identity, explicit size, and concentration.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse


_UNSAFE_PACKAGING = re.compile(
    r"\b(?:refill|nachfullung|nachfullpackung|recharge|tester|testeur|"
    r"sample|probe|decant|gift\s*set|coffret|bundle|discovery\s*set)\b",
    re.I,
)
_CONCENTRATION_PATTERNS = (
    (re.compile(r"\b(?:extrait de parfum|parfum intense|extrait)\b", re.I), "extrait de parfum"),
    (re.compile(r"\b(?:eau de parfum intense|edp intense)\b", re.I), "eau de parfum intense"),
    (re.compile(r"\b(?:eau de toilette intense|edt intense)\b", re.I), "eau de toilette intense"),
    (re.compile(r"\b(?:eau de parfum|edp)\b", re.I), "eau de parfum"),
    (re.compile(r"\b(?:eau de toilette|edt)\b", re.I), "eau de toilette"),
    (re.compile(r"\b(?:eau de cologne|edc)\b", re.I), "eau de cologne"),
    (re.compile(r"\bparfum\b", re.I), "parfum"),
)


def _norm(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold().replace("&", " and ")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _concentration(value: Any) -> str | None:
    text = str(value or "")
    for pattern, canonical in _CONCENTRATION_PATTERNS:
        if pattern.search(text):
            return canonical
    return None


def _identity_name(value: Any, brand: Any) -> str:
    text = _norm(value)
    brand_norm = _norm(brand)
    if brand_norm and text.startswith(brand_norm + " "):
        text = text[len(brand_norm):]
    text = re.sub(
        r"\b\d+(?:[.,]\d+)?\s*(?:ml|cl|dl|l|oz|fl oz)\b",
        " ",
        text,
    )
    for pattern, _ in _CONCENTRATION_PATTERNS:
        text = pattern.sub(" ", text)
    text = re.sub(
        r"\b(?:for men|for women|men|man|women|woman|herren|damen|unisex)\b",
        " ",
        text,
    )
    return re.sub(r"\s+", " ", text).strip()


def _retailer_domain(url: Any) -> str | None:
    try:
        parsed = urlparse(str(url or ""))
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.casefold().removeprefix("www.")
    return host or None


def _explicit_size(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        size = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    if not size.is_integer() or size <= 0 or size > 5000:
        return None
    return int(size)


def _stable_variant_id(product_id: str, size_ml: int, concentration: str) -> str:
    key = f"{product_id}|{size_ml}|{concentration}|bottle"
    return "VAR-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def learn_variants(
    catalog: Mapping[str, Any],
    observations: Iterable[Mapping[str, Any]],
    *,
    min_retailers: int = 2,
) -> dict[str, Any]:
    """Return a copied catalog plus auditable additions; never mutate input.

    Observations should contain product_id, name, brand, size_ml, retailer, and
    product_url. Shadow report rows may provide candidate_product_ids instead
    of product_id; those are accepted only when exactly one candidate exists.
    """
    if min_retailers < 2:
        raise ValueError("min_retailers must be at least 2")
    if not isinstance(catalog, Mapping):
        raise ValueError("catalog root must be an object")
    products = catalog.get("products")
    variants = catalog.get("variants")
    if not isinstance(products, list) or not isinstance(variants, list):
        raise ValueError("catalog must contain products and variants arrays")

    product_by_id = {
        str(row.get("product_id")): row
        for row in products
        if isinstance(row, Mapping) and row.get("product_id")
    }
    existing = {
        (str(row.get("product_id")), _explicit_size(row.get("size_ml")))
        for row in variants
        if isinstance(row, Mapping)
    }

    evidence: dict[tuple[str, int, str], dict[str, Any]] = {}
    rejected: dict[str, int] = defaultdict(int)
    for item in observations:
        if not isinstance(item, Mapping):
            rejected["invalid_observation"] += 1
            continue
        product_id = str(item.get("product_id") or "").strip()
        candidates = item.get("candidate_product_ids")
        if not product_id and isinstance(candidates, list) and len(candidates) == 1:
            product_id = str(candidates[0] or "").strip()
        if not product_id or product_id not in product_by_id:
            rejected["no_unique_existing_product"] += 1
            continue

        product = product_by_id[product_id]
        size = _explicit_size(item.get("size_ml"))
        retailer = str(item.get("retailer") or "").strip()
        url = str(item.get("product_url") or item.get("url") or "").strip()
        domain = _retailer_domain(url)
        brand = str(item.get("brand") or "").strip()
        name = str(item.get("name") or item.get("raw_name") or "").strip()
        product_brand = str(product.get("brand_name") or "").strip()
        product_name = str(product.get("canonical_name") or product.get("name") or "").strip()
        offer_concentration = _concentration(name)
        canonical_concentration = _concentration(product.get("concentration"))

        if not size or not retailer or not domain or not name or not product_brand or not product_name:
            rejected["missing_required_evidence"] += 1
            continue
        if brand and _norm(brand) != _norm(product_brand):
            rejected["brand_conflict"] += 1
            continue
        if _identity_name(name, brand or product_brand) != _identity_name(product_name, product_brand):
            rejected["product_name_conflict"] += 1
            continue
        if not offer_concentration or not canonical_concentration or offer_concentration != canonical_concentration:
            rejected["concentration_unverified_or_conflict"] += 1
            continue
        if _UNSAFE_PACKAGING.search(name) or _UNSAFE_PACKAGING.search(url):
            rejected["special_packaging_requires_review"] += 1
            continue
        if (product_id, size) in existing:
            rejected["variant_already_exists"] += 1
            continue

        key = (product_id, size, offer_concentration)
        bucket = evidence.setdefault(key, {
            "product_id": product_id,
            "size_ml": size,
            "concentration": offer_concentration,
            "retailers": {},
        })
        bucket["retailers"].setdefault(domain, {
            "retailer": retailer,
            "product_url": url,
            "name": name,
        })

    updated = json.loads(json.dumps(catalog))
    added = []
    for key, bucket in sorted(evidence.items()):
        retailer_evidence = list(bucket["retailers"].values())
        if len(retailer_evidence) < min_retailers:
            rejected["insufficient_independent_retailers"] += 1
            continue
        product_id, size, concentration = key
        variant_id = _stable_variant_id(product_id, size, concentration)
        if any(
            isinstance(row, Mapping) and str(row.get("variant_id") or "") == variant_id
            for row in updated["variants"]
        ):
            rejected["variant_id_collision"] += 1
            continue
        names = list(dict.fromkeys(str(row["name"]).strip() for row in retailer_evidence if row.get("name")))
        variant = {
            "variant_id": variant_id,
            "product_id": product_id,
            "size_ml": size,
            "aliases": names,
        }
        updated["variants"].append(variant)
        added.append({
            **variant,
            "concentration": concentration,
            "independent_retailer_count": len(retailer_evidence),
            "evidence": retailer_evidence,
        })

    return {
        "catalog": updated,
        "report": {
            "schema_version": 1,
            "mode": "evidence-backed-variant-learning",
            "catalog_mutated": False,
            "automatic_product_creation": False,
            "product_merges": 0,
            "minimum_independent_retailers": min_retailers,
            "variants_added": len(added),
            "added_variants": added,
            "rejected_observation_counts": dict(sorted(rejected.items())),
        },
    }


def learn_from_shadow_report(catalog: Mapping[str, Any], report: Mapping[str, Any]) -> dict[str, Any]:
    """Consume unresolved examples from a production shadow report."""
    observations = []
    queries = report.get("queries", []) if isinstance(report.get("queries"), list) else []
    for query in queries:
        if not isinstance(query, Mapping):
            continue
        retailers = query.get("retailers", []) if isinstance(query.get("retailers"), list) else []
        for retailer_report in retailers:
            if not isinstance(retailer_report, Mapping):
                continue
            retailer = str(retailer_report.get("retailer") or "").strip()
            examples = retailer_report.get("unresolved_examples", [])
            if not isinstance(examples, list):
                continue
            for example in examples:
                if not isinstance(example, Mapping):
                    continue
                observations.append({**example, "retailer": retailer})
    return learn_variants(catalog, observations)
