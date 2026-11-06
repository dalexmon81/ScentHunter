"""One-shot, read-only preflight for the authorized Notino CJ/VIV XML feed.

This script performs one bounded feed request, inspects exact Dior Sauvage EDP
100 ml candidates, and prints only a sanitized summary. It never writes a DB,
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


TARGET_BRAND = "christian dior"
TARGET_FRAGRANCE = "sauvage"
TARGET_CONCENTRATION = "edp"
TARGET_SIZE_ML = 100.0
PUBLISHABLE_AVAILABILITY = {"in_stock", "out_of_stock"}


def summarize_candidates(records: list[OfferRecord]) -> dict:
    exact = []
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
        exact.append({
            "brand": record.brand,
            "fragrance": record.fragrance,
            "concentration": record.concentration,
            "size_ml": float(record.size_ml),
            "price": str(record.price) if record.price is not None else None,
            "currency": record.currency,
            "availability": record.availability,
            "product_url": record.url,
            "url_host": (parsed.hostname or "").lower(),
            "validation_errors": list(errors),
            "valid_offer_evidence": bool(valid),
            "explicit_publishable_availability": record.availability in PUBLISHABLE_AVAILABILITY,
        })

    if not exact:
        status = "no_exact_product"
    elif len(exact) > 1:
        status = "multiple_exact_candidates_review"
    elif not exact[0]["valid_offer_evidence"] and set(exact[0]["validation_errors"]) != {"invalid_availability"}:
        status = "candidate_invalid"
    elif not exact[0]["explicit_publishable_availability"]:
        status = "candidate_requires_availability_review"
    else:
        status = "ready_for_staging_review"

    return {
        "status": status,
        "source": "cj_viv_authorized_xml",
        "catalog_candidates": len(records),
        "exact_candidate_count": len(exact),
        "ready_for_staging_review": status == "ready_for_staging_review",
        "candidates": exact,
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
