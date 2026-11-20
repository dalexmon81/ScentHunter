"""Read-only full-feed Notino coverage audit.

Downloads the authorized CJ/VIV snapshot once, reports aggregate parser and
canonical-matching coverage, and never stages or modifies offers.
"""
from __future__ import annotations

import json
import os
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.connectors.notino_feed import NotinoAffiliateFeedConnector
from app.db import make_engine
from app.models import Offer, Store
from app.services.canonical_matching import resolve_canonical_variant
from scrapers.notino import affiliate_feed
from scenthunter_next_engine.next_engine_service import NextEngineService
from scenthunter_next_engine.offer_normalizer import normalize_offer

CATALOG_PATH = Path("/app/backend/product_catalog.json")


def main() -> int:
    required = (
        "NOTINO_CJ_FEED_USERNAME",
        "NOTINO_CJ_FEED_PASSWORD",
    )
    missing = [key for key in required if not os.environ.get(key) and not os.environ.get(
        "CJ_HTTP_USERNAME" if key.endswith("USERNAME") else "CJ_HTTP_PASSWORD"
    )]
    if missing:
        raise SystemExit("NOTINO_AUDIT_CREDENTIALS_MISSING=" + ",".join(missing))
    if not CATALOG_PATH.is_file():
        raise SystemExit("NOTINO_AUDIT_LEGACY_CATALOG_MISSING")

    started = datetime.now(timezone.utc)
    stats: dict = {}
    connector = NotinoAffiliateFeedConnector(cache_ttl_seconds=0)
    engine = make_engine()
    try:
        with tempfile.TemporaryFile(mode="w+b") as payload:
            downloaded_bytes = affiliate_feed._download_feed(payload)
            payload.seek(0)
            data = payload.read()
        offers = affiliate_feed.parse_feed(data, stats=stats)

        matcher = NextEngineService.from_catalog_file(CATALOG_PATH)
        parser_validation = Counter()
        normalization_errors = Counter()
        database_reasons = Counter()
        legacy_input = []
        unique_external_ids = set()
        id_counts = Counter()
        active_offer_ids = set()
        db_match_count = 0
        db_match_valid_count = 0
        valid_connector_count = 0
        invalid_connector_count = 0
        records_without_gtin = 0
        records_with_gtin = 0
        gtin_values = set()
        legacy_valid_input = 0

        with Session(engine) as session:
            store = session.scalar(select(Store).where(Store.slug == "notino"))
            if store is None:
                raise SystemExit("NOTINO_AUDIT_STORE_NOT_FOUND")
            store_id = store.id
            active_offer_ids = set(session.scalars(
                select(Offer.external_product_id).where(
                    Offer.store_id == store_id,
                    Offer.status == "active",
                    Offer.external_product_id.is_not(None),
                )
            ).all())

            for offer in offers:
                record = connector._to_record(offer)
                external_id = str(record.get("external_product_id") or "").strip()
                if external_id:
                    unique_external_ids.add(external_id)
                    id_counts[external_id] += 1
                gtin = str(record.get("gtin") or "").strip()
                if gtin:
                    records_with_gtin += 1
                    gtin_values.add(gtin)
                else:
                    records_without_gtin += 1

                parsed = connector.parse_raw(record)
                validation = connector.validate_offer(parsed)
                if validation.valid and parsed.get("currency_explicit") is True:
                    valid_connector_count += 1
                else:
                    invalid_connector_count += 1
                    for reason in (validation.errors or ("currency_not_explicit_in_source",)):
                        parser_validation[reason] += 1

                try:
                    normalized = normalize_offer(parsed, retailer=connector.store_key)
                except (TypeError, ValueError, ArithmeticError) as exc:
                    normalization_errors[type(exc).__name__] += 1
                    continue

                canonical = resolve_canonical_variant(
                    session,
                    store_id=store_id,
                    external_product_id=external_id or None,
                    record=dict(parsed),
                )
                if canonical.match is not None:
                    db_match_count += 1
                    if validation.valid and parsed.get("currency_explicit") is True:
                        db_match_valid_count += 1
                    database_reasons["matched:" + canonical.match.method] += 1
                    continue

                database_reasons[canonical.reason] += 1
                # The real persistence path falls back to the legacy catalog
                # matcher only for this one reason. Other canonical failures
                # are deliberately held for review.
                if canonical.reason == "no_canonical_variant_match":
                    legacy_input.append(normalized)
                    if validation.valid and parsed.get("currency_explicit") is True:
                        legacy_valid_input += 1

        legacy_summary = {
            "input_records": len(legacy_input),
            "connector_valid_records": legacy_valid_input,
            "matched_records": 0,
            "unresolved_records": 0,
            "ambiguous_records": 0,
            "unresolved_reasons": {},
            "ambiguous_reasons": {},
        }
        if legacy_input:
            aggregation = matcher.process_offers(legacy_input)
            legacy_summary["matched_records"] = int(aggregation.matched_offer_count)
            legacy_summary["unresolved_records"] = len(aggregation.unresolved)
            legacy_summary["ambiguous_records"] = len(aggregation.ambiguous)
            legacy_summary["unresolved_reasons"] = dict(sorted(Counter(
                item.reason or item.status.value for item in aggregation.unresolved
            ).items()))
            legacy_summary["ambiguous_reasons"] = dict(sorted(Counter(
                item.reason or item.status.value for item in aggregation.ambiguous
            ).items()))

        duplicate_ids = sum(count - 1 for count in id_counts.values() if count > 1)
        report = {
            "audit": "read_only_notino_full_feed_coverage",
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "feed": {
                "downloaded_bytes": downloaded_bytes,
                "candidate_rows_scanned": int(stats.get("products_read", 0)),
                "parser_valid_rows_before_deduplication": int(stats.get("valid_items", 0)),
                "parser_rejected_rows": int(stats.get("rejected_items", 0)),
                "parser_rejection_reasons": stats.get("rejection_reasons", {}),
                "unique_parsed_offers_after_deduplication": len(offers),
                "deduplicated_rows": max(
                    0, int(stats.get("valid_items", 0)) - len(offers)
                ),
                "unique_external_product_ids": len(unique_external_ids),
                "duplicate_external_id_occurrences": duplicate_ids,
                "records_with_gtin": records_with_gtin,
                "records_without_gtin": records_without_gtin,
                "unique_gtins": len(gtin_values),
            },
            "publication_gate": {
                "connector_valid_and_explicit_currency": valid_connector_count,
                "connector_invalid_or_currency_unproven": invalid_connector_count,
                "validation_reasons": dict(sorted(parser_validation.items())),
                "normalization_errors": dict(sorted(normalization_errors.items())),
            },
            "canonical_database_match": {
                "matched_records": db_match_count,
                "matched_and_connector_valid": db_match_valid_count,
                "outcomes": dict(sorted(database_reasons.items())),
            },
            "legacy_catalog_fallback": legacy_summary,
            "existing_catalog_overlap": {
                "active_notino_offer_external_ids": len(active_offer_ids),
                "feed_ids_already_active": len(unique_external_ids & active_offer_ids),
                "feed_ids_not_yet_active": len(unique_external_ids - active_offer_ids),
            },
            "safety": {
                "database_writes": 0,
                "offers_created_or_updated": 0,
                "staging_rows_created": 0,
                "publication_rules_changed": 0,
            },
        }
        print("NOTINO_FULL_FEED_AUDIT_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
