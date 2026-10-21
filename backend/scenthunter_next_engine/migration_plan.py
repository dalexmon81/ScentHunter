"""Shared deterministic planning and preflight for API and CLI legacy migrations.

This module never opens a database and never writes to a repository. Its output is
an auditable disposition for every source row, so preview and apply can use the
same rules and snapshot.
"""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


TRACKING_KEYS = frozenset({"gclid", "fbclid", "msclkid", "yclid"})
LISTING_SEGMENTS = frozenset({
    "collection", "collections", "category", "categories", "categorie",
    "categorias", "kategorie", "catalog", "catalogue", "search", "suche",
    "tag", "tags", "brand", "brands", "brands-list", "manufacturer",
    "manufacturers", "blog", "blogs", "news", "article", "articles",
})
CRAWLER_FILES = frozenset({"agents.md", "robots.txt", "sitemap.xml", "humans.txt"})


def normalize_store(value: Any) -> str:
    return str(value or "").strip().casefold()


def normalize_url(value: Any) -> str:
    """Normalize only URL components that are safe for retailer-page identity.

    Meaningful query parameters are retained. Common tracking parameters and
    fragments are removed; host casing/default ports and a trailing slash are
    normalized. This is a pairing key, not proof that two pages are equivalent.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
        if parts.scheme.casefold() not in {"http", "https"} or not parts.hostname:
            return raw
        scheme = parts.scheme.casefold()
        host = parts.hostname.casefold()
        port = parts.port
        if port and not ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
            host = f"{host}:{port}"
        if parts.username or parts.password:
            return raw
        path = re.sub(r"/{2,}", "/", parts.path or "/")
        if path != "/":
            path = path.rstrip("/")
        query = [
            (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
            if k.casefold() not in TRACKING_KEYS and not k.casefold().startswith("utm_")
        ]
        query.sort(key=lambda item: (item[0], item[1]))
        return urlunsplit((scheme, host, path, urlencode(query, doseq=True), ""))
    except (ValueError, UnicodeError):
        return raw


def _source_url(product: Mapping[str, Any], variant: Mapping[str, Any] | None = None) -> str:
    variant = variant or {}
    return str(variant.get("variant_url") or variant.get("url") or product.get("url") or "").strip()


def _has_price(product: Mapping[str, Any], variant: Mapping[str, Any] | None = None) -> bool:
    variant = variant or {}
    value = variant.get("price")
    if value in (None, ""):
        value = product.get("price")
    return value not in (None, "")


def non_product_reason(product: Mapping[str, Any], variant: Mapping[str, Any] | None = None) -> str | None:
    """Return a reason only for high-confidence non-product URLs.

    URL patterns are evidence, not proof. A listing-looking page with a price is
    kept for field validation and then quarantined/reviewed if ambiguous.
    """
    url = _source_url(product, variant)
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    path = parts.path.casefold().rstrip("/")
    filename = path.rsplit("/", 1)[-1]
    if filename in CRAWLER_FILES:
        return "crawler_control_file"
    segments = [segment for segment in path.split("/") if segment]
    if any(segment in LISTING_SEGMENTS for segment in segments) and not _has_price(product, variant):
        return "listing_or_navigation_url_without_price"
    if filename.endswith(("-parfum.html", "-perfume.html", "-haartools.html", "-kosmetik.html")) and not _has_price(product, variant):
        return "listing_suffix_without_price"
    return None


def _quarantine(kind: str, reason: str, store: str | None, url: str | None,
                source_table: str, source_index: int, row: Any) -> dict[str, Any]:
    safe_row = row if isinstance(row, Mapping) else {"value_type": type(row).__name__, "value": repr(row)[:500]}
    payload = json.dumps(safe_row, ensure_ascii=False, sort_keys=True, default=str)
    return {
        "class": kind,
        "reason": reason,
        "store": store,
        "url": url,
        "source_table": source_table,
        "source_index": source_index,
        "row_sha256": sha256(payload.encode("utf-8")).hexdigest(),
        "row": dict(safe_row),
    }


def build_entries(products: Sequence[Any], variants: Sequence[Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Pair rows consistently and quarantine every malformed/ambiguous/orphan row."""
    base_by_key: dict[tuple[str, str], list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    variants_by_key: dict[tuple[str, str], list[tuple[int, Mapping[str, Any]]]] = defaultdict(list)
    quarantine: list[dict[str, Any]] = []

    for index, row in enumerate(products):
        if not isinstance(row, Mapping):
            quarantine.append(_quarantine("TECHNICAL_FAILURE", "product_row_not_an_object", None, None, "store_products", index, row))
            continue
        store, url = normalize_store(row.get("store")), normalize_url(row.get("url"))
        if not store or not url:
            quarantine.append(_quarantine("INCOMPLETE", "product_row_missing_store_or_url", store or None, str(row.get("url") or "") or None, "store_products", index, row))
            continue
        base_by_key[(store, url)].append((index, row))

    for index, row in enumerate(variants):
        if not isinstance(row, Mapping):
            quarantine.append(_quarantine("TECHNICAL_FAILURE", "variant_row_not_an_object", None, None, "store_product_variants", index, row))
            continue
        store, url = normalize_store(row.get("store")), normalize_url(row.get("url"))
        if not store or not url:
            quarantine.append(_quarantine("INCOMPLETE", "variant_row_missing_store_or_url", store or None, str(row.get("url") or "") or None, "store_product_variants", index, row))
            continue
        variants_by_key[(store, url)].append((index, row))

    entries: list[dict[str, Any]] = []
    paired = 0
    duplicate_product_rows = 0
    orphan_variant_rows = 0
    ambiguous_variant_rows = 0
    for key, group in base_by_key.items():
        if len(group) != 1:
            duplicate_product_rows += len(group)
            for source_index, row in group:
                quarantine.append(_quarantine("DUPLICATE_OR_AMBIGUOUS", "duplicate_normalized_store_url_product_key", key[0], str(row.get("url") or ""), "store_products", source_index, row))
            for source_index, row in variants_by_key.get(key, []):
                ambiguous_variant_rows += 1
                quarantine.append(_quarantine("DUPLICATE_OR_AMBIGUOUS", "variant_matches_duplicate_product_key", key[0], str(row.get("url") or ""), "store_product_variants", source_index, row))
            continue
        source_index, product = group[0]
        matched = variants_by_key.get(key, [])
        if matched:
            for variant_index, variant in matched:
                entries.append({"store": key[0], "product_row": dict(product), "variant_row": dict(variant),
                                "source_product_index": source_index, "source_variant_index": variant_index})
                paired += 1
        else:
            entries.append({"store": key[0], "product_row": dict(product), "variant_row": None,
                            "source_product_index": source_index, "source_variant_index": None})

    for key, group in variants_by_key.items():
        if key not in base_by_key:
            orphan_variant_rows += len(group)
            for source_index, row in group:
                quarantine.append(_quarantine("DUPLICATE_OR_AMBIGUOUS", "orphan_variant_without_product_row", key[0], str(row.get("url") or ""), "store_product_variants", source_index, row))

    stats = {
        "products_rows": len(products),
        "variant_rows": len(variants),
        "candidate_observations": len(entries),
        "paired_variant_rows": paired,
        "duplicate_product_rows": duplicate_product_rows,
        "orphan_variant_rows": orphan_variant_rows,
        "variants_under_ambiguous_product_keys": ambiguous_variant_rows,
        "malformed_product_rows": sum(1 for q in quarantine if q["source_table"] == "store_products" and q["class"] == "TECHNICAL_FAILURE"),
        "malformed_variant_rows": sum(1 for q in quarantine if q["source_table"] == "store_product_variants" and q["class"] == "TECHNICAL_FAILURE"),
    }
    return entries, stats, quarantine


def preflight_entries(entries: Sequence[Mapping[str, Any]], pairing_quarantine: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """Validate all candidates without writes and produce a complete disposition ledger."""
    accepted: list[dict[str, Any]] = []
    quarantine: list[dict[str, Any]] = [dict(item) for item in pairing_quarantine]
    dispositions: list[dict[str, Any]] = [dict(item) for item in pairing_quarantine]
    counts: dict[str, int] = defaultdict(int)
    for item in pairing_quarantine:
        counts[str(item.get("class") or "TECHNICAL_FAILURE")] += 1
    for index, entry in enumerate(entries):
        product = entry.get("product_row")
        variant = entry.get("variant_row") if isinstance(entry.get("variant_row"), Mapping) else None
        store = normalize_store(entry.get("store"))
        url = _source_url(product if isinstance(product, Mapping) else {}, variant)
        if not isinstance(product, Mapping) or not store:
            counts["TECHNICAL_FAILURE"] += 1
            item = _quarantine("TECHNICAL_FAILURE", "candidate_missing_product_or_store", store or None, url or None, "candidate_entries", index, entry)
            quarantine.append(item); dispositions.append(item)
            continue
        # Reject known placeholder/invalid price observations before creating offers.
        fetch_status = str(
            (variant or {}).get("fetch_status") or product.get("fetch_status") or ""
        ).strip().casefold()
        invalid_price_statuses = {
            "invalid_placeholder_price", "invalid_price", "placeholder_price",
            "price_invalid", "invalid", "error", "failed",
        }
        if fetch_status in invalid_price_statuses:
            counts["INCOMPLETE"] += 1
            item = _quarantine(
                "INCOMPLETE", f"source_fetch_status_rejects_price:{fetch_status}",
                store, url or None, "candidate_entries", index, entry,
            )
            quarantine.append(item); dispositions.append(item)
            continue

        non_product = non_product_reason(product, variant)
        if non_product:
            counts["NON_PRODUCT_CONFIRMED"] += 1
            item = _quarantine("NON_PRODUCT_CONFIRMED", non_product, store, url or None, "candidate_entries", index, entry)
            quarantine.append(item); dispositions.append(item)
            continue
        # A price does not turn a category/search/brand page into a product page.
        try:
            url_parts = urlsplit(url)
            url_path = url_parts.path.casefold()
            path_segments = [segment for segment in url_path.split("/") if segment]
        except ValueError:
            url_path = ""
            path_segments = []
        listing_suffix = url_path.rsplit("/", 1)[-1].endswith(("-parfum.html", "-perfume.html", "-haartools.html", "-kosmetik.html")) if url_path else False
        if any(segment in LISTING_SEGMENTS for segment in path_segments) or listing_suffix:
            counts["IDENTITY_REVIEW"] += 1
            item = _quarantine("IDENTITY_REVIEW", "listing_or_navigation_pattern_requires_manual_review_even_if_priced", store, url or None, "candidate_entries", index, entry)
            quarantine.append(item); dispositions.append(item)
            continue
        title = str((variant or {}).get("name") or product.get("name") or "").strip()
        brand = str((variant or {}).get("brand") or product.get("brand") or "").strip()
        base_brand = str(product.get("brand") or "").strip()
        variant_brand = str((variant or {}).get("brand") or "").strip()
        if base_brand and variant_brand and base_brand.casefold() != variant_brand.casefold():
            counts["IDENTITY_REVIEW"] += 1
            item = _quarantine("IDENTITY_REVIEW", "base_product_brand_conflicts_with_variant_brand", store, url or None, "candidate_entries", index, entry)
            quarantine.append(item); dispositions.append(item)
            continue
        if not _has_price(product, variant):
            counts["INCOMPLETE"] += 1
            item = _quarantine("INCOMPLETE", "commercial_candidate_missing_price", store, url or None, "candidate_entries", index, entry)
            quarantine.append(item); dispositions.append(item)
            continue
        discriminator_fields = ("sku", "gtin", "mpn", "size_ml", "concentration", "variant_key")
        source_rows = [product] + ([variant] if variant else [])
        if not any(str(row.get(field) or "").strip() for row in source_rows for field in discriminator_fields):
            counts["IDENTITY_REVIEW"] += 1
            item = _quarantine("IDENTITY_REVIEW", "no_source_variant_discriminator_sku_gtin_mpn_size_or_concentration", store, url or None, "candidate_entries", index, entry)
            quarantine.append(item); dispositions.append(item)
            continue
        try:
            from .legacy_bridge import observation_from_legacy_rows
            observation = observation_from_legacy_rows(
                store=store, product_row=product, variant_row=variant,
                trace_id="legacy-snapshot-v1", parser_version="legacy-row-v1",
            )
            # Mapping is only a structural validation; it is not proof of cross-retailer identity.
            accepted.append({"entry": dict(entry), "observation": observation, "candidate_index": index})
            counts["COMMERCIAL_VALID"] += 1
            encoded = json.dumps(entry, ensure_ascii=False, sort_keys=True, default=str)
            dispositions.append({"class": "COMMERCIAL_VALID", "reason": "all_required_fields_validated; identity equivalence not inferred across retailers",
                                 "store": store, "url": url or None, "source_table": "candidate_entries",
                                 "source_index": index, "row_sha256": sha256(encoded.encode("utf-8")).hexdigest()})
        except Exception as exc:
            counts["INCOMPLETE"] += 1
            item = _quarantine("INCOMPLETE", f"row_validation_failed:{type(exc).__name__}:{str(exc)[:500]}", store, url or None, "candidate_entries", index, entry)
            quarantine.append(item); dispositions.append(item)

    total = len(entries) + len(pairing_quarantine)
    classified = len(accepted) + len(quarantine)
    # Every candidate source row must have one disposition; paired variant entries are
    # candidate offers, while pairing-level rejects are separate source rows.
    blocking_quarantine = [item for item in quarantine if item.get("class") != "NON_PRODUCT_CONFIRMED"]
    report = {
        "processed_candidates": len(entries),
        "valid_candidates": len(accepted),
        "quarantined_records": len(quarantine),
        "blocking_rejections": len(blocking_quarantine),
        "confirmed_non_products": sum(1 for item in quarantine if item.get("class") == "NON_PRODUCT_CONFIRMED"),
        "classified_records": len(dispositions),
        "all_candidates_classified": True,
        "safe_to_apply": bool(accepted) and not blocking_quarantine,
        "validation": "complete",
        "class_counts": dict(sorted(counts.items())),
        "quarantine_count": len(quarantine),
        "quarantine_sample": quarantine[:50],
        "quarantine_sha256": sha256(json.dumps(quarantine, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest(),
        "_accepted": accepted,
        "_quarantine": quarantine,
        "_dispositions": dispositions,
    }
    return report


def snapshot_digest(snapshot: Mapping[str, Any]) -> str:
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return sha256(canonical.encode("utf-8")).hexdigest()
