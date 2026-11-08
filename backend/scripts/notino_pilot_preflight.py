"""One-shot, read-only preflight for the authorized Notino CJ/VIV XML feed.

This script performs one bounded feed request, inspects the exact Liquid Brun
EDP 100 ml identity, checks its independently verified GTIN, and prints only
a sanitized summary. It never writes a DB,
never prints credentials or raw XML, and never publishes an offer.
"""
from __future__ import annotations

import asyncio
import json
import sys
from urllib.parse import urlparse

from app.connectors.base import OfferRecord, validate_offer
from app.connectors.notino import NotinoAffiliateFeedConnector
from app.services.product_normalization import normalize_brand


TARGET_BRAND = "french avenue"
TARGET_FRAGRANCE = "liquid brun"
TARGET_CONCENTRATION = "edp"
TARGET_SIZE_ML = 100.0
# Verified on the Bplatz product page; a Notino feed row must independently
# carry this same identifier before it can pass the exact-product preflight.
TARGET_GTIN = "6290360375694"
PUBLISHABLE_AVAILABILITY = {"in_stock", "out_of_stock"}


def summarize_candidates(records: list[OfferRecord]) -> dict:
    identity_candidates = []
    for record in records:
        if normalize_brand(record.brand) != TARGET_BRAND:
            continue
        if record.fragrance != TARGET_FRAGRANCE:
            continue
        if record.concentration != TARGET_CONCENTRATION:
            continue
        if record.size_ml is None or abs(float(record.size_ml) - TARGET_SIZE_ML) > 0.01:
            continue
        valid, errors = validate_offer(record)
        parsed = urlparse(record.url)
        identity_candidates.append({
            "brand": record.brand,
            "fragrance": record.fragrance,
            "concentration": record.concentration,
            "size_ml": float(record.size_ml),
            "gtin": record.gtin,
            "gtin_match": record.gtin == TARGET_GTIN,
            "price": str(record.price) if record.price is not None else None,
            "currency": record.currency,
            "availability": record.availability,
            "product_url": record.url,
            "url_host": (parsed.hostname or "").lower(),
            "validation_errors": list(errors),
            "valid_offer_evidence": bool(valid),
            "explicit_publishable_availability": record.availability in PUBLISHABLE_AVAILABILITY,
        })

    if not identity_candidates:
        status = "no_exact_product"
    elif len(identity_candidates) > 1:
        status = "multiple_exact_candidates_review"
    elif not identity_candidates[0]["gtin"]:
        status = "candidate_requires_gtin_review"
    elif not identity_candidates[0]["gtin_match"]:
        status = "candidate_gtin_mismatch"
    elif not identity_candidates[0]["valid_offer_evidence"] and set(identity_candidates[0]["validation_errors"]) != {"invalid_availability"}:
        status = "candidate_invalid"
    elif not identity_candidates[0]["explicit_publishable_availability"]:
        status = "candidate_requires_availability_review"
    else:
        status = "ready_for_staging_review"

    return {
        "status": status,
        "source": "cj_viv_authorized_xml",
        "catalog_candidates": len(records),
        "exact_candidate_count": len(identity_candidates),
        "ready_for_staging_review": status == "ready_for_staging_review",
        "candidates": identity_candidates,
        "database_written": False,
        "offer_published": False,
    }


def main() -> int:
    connector = NotinoAffiliateFeedConnector()
    try:
        asyncio.run(connector.discover_products())
        records = list(connector._offers)
        report = summarize_candidates(records)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        # FeedImportError messages are stable, sanitized codes. Do not print
        # arbitrary exception text because network libraries may include URLs.
        from scrapers.notino.affiliate_feed import FeedImportError
        if isinstance(exc, FeedImportError):
            error = str(exc)
        else:
            error = "notino_preflight_unexpected_error"
        print(json.dumps({
            "status": "blocked",
            "error": error,
            "database_written": False,
            "offer_published": False,
        }, ensure_ascii=False, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
