"""Read-only full Notino CJ feed audit, processed on the GitHub runner.

The isolated Fly pilot is used only to download the authorized CJ feed and to
create a consistent SQLite backup. Parsing and matching run locally.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import tempfile
import time
from collections import Counter
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
os.chdir(BACKEND)

FEED_BEGIN = b"NOTINO_FEED_BEGIN"
FEED_END = b"NOTINO_FEED_END="
DB_BEGIN = b"NOTINO_DB_BEGIN"
DB_END = b"NOTINO_DB_END="


def _remote_transfer(remote_python: str, begin: bytes, end: bytes, destination: Path, timeout: int) -> int:
    encoded = base64.b64encode(remote_python.encode("utf-8")).decode("ascii")
    command = f"/bin/sh -lc 'printf %s {encoded} | base64 -d | /app/.venv/bin/python'"
    app = os.environ.get("SCENTHUNTER_NOTINO_FEED_APP", "scenthunter-pilot-20261030").strip()
    if not app:
        raise RuntimeError("SCENTHUNTER_NOTINO_FEED_APP_missing")

    with tempfile.TemporaryFile() as transport, tempfile.TemporaryFile() as errors:
        result = subprocess.run(
            ["flyctl", "ssh", "console", "--app", app, "--select=false", "-C", command],
            stdout=transport, stderr=errors, timeout=timeout, check=False,
        )
        if result.returncode:
            errors.seek(0)
            detail = errors.read(4000).decode("utf-8", "replace")
            raise RuntimeError(f"pilot_read_failed:{result.returncode}:{detail}")

        transport.seek(0)
        for line in transport:
            if line.rstrip(b"\r\n") == begin:
                break
        else:
            raise RuntimeError("pilot_transfer_start_marker_missing")

        digest = hashlib.sha256()
        size = 0
        with destination.open("wb") as output:
            for line in transport:
                if line.startswith(end):
                    expected_size, expected_digest = line[len(end):].strip().split(b":", 1)
                    if size != int(expected_size) or digest.hexdigest().encode() != expected_digest:
                        raise RuntimeError("pilot_transfer_checksum_mismatch")
                    return size
                chunk = base64.b64decode(line.strip(), validate=True)
                size += len(chunk)
                if size > 512 * 1024 * 1024:
                    raise RuntimeError("pilot_transfer_exceeds_512mb")
                digest.update(chunk)
                output.write(chunk)
        raise RuntimeError("pilot_transfer_incomplete")


def download_feed(destination: Path) -> int:
    remote = r'''
import base64, hashlib, sys, tempfile, time
from scrapers.notino import affiliate_feed
with tempfile.TemporaryFile() as source:
    size = affiliate_feed._download_feed(source, time.monotonic() + 300)
    source.seek(0)
    digest = hashlib.sha256()
    out = sys.stdout.buffer
    out.write(b"NOTINO_FEED_BEGIN" + bytes([10]))
    while True:
        chunk = source.read(65535)
        if not chunk:
            break
        digest.update(chunk)
        out.write(base64.b64encode(chunk) + bytes([10]))
    out.write(b"NOTINO_FEED_END=" + str(size).encode() + b":" + digest.hexdigest().encode() + bytes([10]))
    out.flush()
'''
    return _remote_transfer(remote, FEED_BEGIN, FEED_END, destination, timeout=1200)


def download_catalog_snapshot(destination: Path) -> int:
    remote = r'''
import base64, hashlib, sqlite3, sys
source = sqlite3.connect("file:/data/catalog/catalog.sqlite3?mode=ro", uri=True, timeout=60)
target = sqlite3.connect(":memory:")
try:
    source.backup(target)
    payload = target.serialize()
finally:
    source.close()
    target.close()
digest = hashlib.sha256(payload)
size = len(payload)
out = sys.stdout.buffer
out.write(b"NOTINO_DB_BEGIN" + bytes([10]))
for offset in range(0, size, 65535):
    out.write(base64.b64encode(payload[offset:offset + 65535]) + bytes([10]))
out.write(b"NOTINO_DB_END=" + str(size).encode() + b":" + digest.hexdigest().encode() + bytes([10]))
out.flush()
'''
    return _remote_transfer(remote, DB_BEGIN, DB_END, destination, timeout=600)


def parse_feed(source, affiliate_feed, started):
    counts = Counter()
    rejected = Counter({
        "missing_title": 0,
        "missing_brand": 0,
        "invalid_or_missing_price": 0,
        "currency_not_eur": 0,
        "invalid_or_missing_fr_product_url": 0,
        "invalid_or_missing_availability": 0,
    })
    unique = {}
    original_items = affiliate_feed._feed_items

    def measured_items(stream):
        for node in original_items(stream):
            counts["candidate_rows_scanned"] += 1
            if counts["candidate_rows_scanned"] % 5000 == 0:
                print("NOTINO_AUDIT_PARSE_PROGRESS=" + json.dumps({
                    "rows": counts["candidate_rows_scanned"],
                    "valid": counts["valid_rows"],
                    "elapsed_seconds": round(time.monotonic() - started, 1),
                }), flush=True)
            yield node

    affiliate_feed._feed_items = measured_items
    try:
        source.seek(0)
        with affiliate_feed._xml_stream(source, time.monotonic() + 25 * 60) as stream:
            for node in affiliate_feed._feed_items(stream):
                fields = affiliate_feed._field_map(node)
                offer = affiliate_feed._parse_item(node, fields)
                if offer is not None:
                    counts["valid_rows"] += 1
                    counts["valid_product_links"] += 1
                    key = (offer.external_id, offer.url, offer.size_ml, offer.gtin or "", offer.sku or "")
                    unique[key] = offer
                    continue

                title = affiliate_feed._first(node, "title", "name", "productname", fields=fields)
                brand = affiliate_feed._first(node, "brand", "manufacturer", "vendor", fields=fields)
                raw_price = affiliate_feed._first(node, "price", "saleprice", "currentprice", fields=fields)
                price, currency = affiliate_feed._money(raw_price)
                currency = currency or affiliate_feed._first(node, "currency", "pricecurrency", fields=fields).upper()
                raw_link = affiliate_feed._first(node, "link", "url", "producturl", fields=fields)

                if not title:
                    rejected["missing_title"] += 1
                if not brand:
                    rejected["missing_brand"] += 1
                if price is None:
                    rejected["invalid_or_missing_price"] += 1
                if currency != "EUR":
                    rejected["currency_not_eur"] += 1
                if affiliate_feed._product_url(raw_link):
                    counts["valid_product_links"] += 1
                else:
                    rejected["invalid_or_missing_fr_product_url"] += 1

                availability = affiliate_feed._first(
                    node, "availability", "stock", "availabilitystatus", fields=fields
                ).lower().strip()
                if availability not in {
                    "in stock", "instock", "in_stock", "available",
                    "limited availability", "limitedavailability",
                    "out of stock", "outofstock", "out_of_stock",
                    "sold out", "unavailable", "preorder", "pre-order",
                }:
                    rejected["invalid_or_missing_availability"] += 1
    finally:
        affiliate_feed._feed_items = original_items

    return list(unique.values()), {
        "candidate_rows_scanned": int(counts["candidate_rows_scanned"]),
        "parser_valid_rows_before_deduplication": int(counts["valid_rows"]),
        "parser_rejected_rows": int(counts["candidate_rows_scanned"] - counts["valid_rows"]),
        "parser_rejection_reasons": dict(sorted(rejected.items())),
        "unique_parsed_offers_after_deduplication": len(unique),
        "deduplicated_rows": max(0, int(counts["valid_rows"]) - len(unique)),
        "valid_product_links": int(counts["valid_product_links"]),
    }


def main() -> int:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="notino-full-feed-audit-") as temp_dir:
        root = Path(temp_dir)
        feed_path = root / "authorized-feed.bin"
        feed_bytes = download_feed(feed_path)
        print("NOTINO_AUDIT_FEED_DOWNLOAD=" + json.dumps({
            "bytes": feed_bytes, "elapsed_seconds": round(time.monotonic() - started, 1)
        }), flush=True)

        from scrapers.notino import affiliate_feed
        with feed_path.open("rb") as source:
            offers, feed_stats = parse_feed(source, affiliate_feed, started)

        db_path = root / "catalog.sqlite3"
        db_bytes = download_catalog_snapshot(db_path)
        os.environ["SCENTHUNTER_CATALOG_DATABASE_URL"] = "sqlite:///" + db_path.as_posix()

        from sqlalchemy import select
        from sqlalchemy.orm import Session
        from app.connectors.notino_feed import NotinoAffiliateFeedConnector
        from app.db import make_engine
        from app.models import Offer, Store
        from app.services.canonical_matching import resolve_canonical_variant
        from scenthunter_next_engine.next_engine_service import NextEngineService
        from scenthunter_next_engine.offer_normalizer import normalize_offer

        connector = NotinoAffiliateFeedConnector(cache_ttl_seconds=0)
        legacy_matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
        engine = make_engine()
        parser_validation = Counter()
        normalization_errors = Counter()
        database_reasons = Counter()
        legacy_input = []
        external_ids = set()
        external_id_counts = Counter()
        gtins = set()
        with_gtin = without_gtin = 0
        connector_valid = connector_invalid = 0
        db_matches = db_matches_valid = legacy_valid = 0

        try:
            with Session(engine) as session:
                store = session.scalar(select(Store).where(Store.slug == "notino-fr"))
                if store is None:
                    raise RuntimeError("NOTINO_AUDIT_STORE_NOT_FOUND")
                active_ids = set(session.scalars(
                    select(Offer.external_product_id).where(
                        Offer.store_id == store.id,
                        Offer.status == "active",
                        Offer.external_product_id.is_not(None),
                    )
                ).all())

                for index, offer in enumerate(offers, start=1):
                    record = connector._to_record(offer)
                    external_id = str(record.get("external_product_id") or "").strip()
                    if external_id:
                        external_ids.add(external_id)
                        external_id_counts[external_id] += 1
                    gtin = str(record.get("gtin") or "").strip()
                    if gtin:
                        with_gtin += 1
                        gtins.add(gtin)
                    else:
                        without_gtin += 1

                    parsed = connector.parse_raw(record)
                    validation = connector.validate_offer(parsed)
                    is_valid = validation.valid and parsed.get("currency_explicit") is True
                    if is_valid:
                        connector_valid += 1
                    else:
                        connector_invalid += 1
                        for reason in (validation.errors or ("currency_not_explicit_in_source",)):
                            parser_validation[reason] += 1

                    try:
                        normalized = normalize_offer(parsed, retailer=connector.store_key)
                    except (TypeError, ValueError, ArithmeticError) as exc:
                        normalization_errors[type(exc).__name__] += 1
                        continue

                    result = resolve_canonical_variant(
                        session, store_id=store.id,
                        external_product_id=external_id or None,
                        record=dict(parsed),
                    )
                    if result.match is not None:
                        db_matches += 1
                        if is_valid:
                            db_matches_valid += 1
                        database_reasons["matched:" + result.match.method] += 1
                    else:
                        database_reasons[result.reason] += 1
                        if result.reason == "no_canonical_variant_match":
                            legacy_input.append(normalized)
                            if is_valid:
                                legacy_valid += 1

                    if index % 5000 == 0:
                        print("NOTINO_AUDIT_MATCH_PROGRESS=" + json.dumps({
                            "records": index, "canonical_matches": db_matches,
                            "elapsed_seconds": round(time.monotonic() - started, 1),
                        }), flush=True)

            legacy_summary = {
                "input_records": len(legacy_input),
                "connector_valid_records": legacy_valid,
                "matched_records": 0,
                "unresolved_records": 0,
                "ambiguous_records": 0,
                "unresolved_reasons": {},
                "ambiguous_reasons": {},
            }
            if legacy_input:
                aggregation = legacy_matcher.process_offers(legacy_input)
                legacy_summary.update({
                    "matched_records": int(aggregation.matched_offer_count),
                    "unresolved_records": len(aggregation.unresolved),
                    "ambiguous_records": len(aggregation.ambiguous),
                    "unresolved_reasons": dict(sorted(Counter(
                        item.reason or item.status.value for item in aggregation.unresolved
                    ).items())),
                    "ambiguous_reasons": dict(sorted(Counter(
                        item.reason or item.status.value for item in aggregation.ambiguous
                    ).items())),
                })

            report = {
                "audit": "read_only_notino_full_feed_coverage",
                "elapsed_seconds": round(time.monotonic() - started, 1),
                "feed": {
                    "downloaded_bytes": feed_bytes,
                    **feed_stats,
                    "unique_external_product_ids": len(external_ids),
                    "duplicate_external_id_occurrences": sum(
                        count - 1 for count in external_id_counts.values() if count > 1
                    ),
                    "records_with_gtin": with_gtin,
                    "records_without_gtin": without_gtin,
                    "unique_gtins": len(gtins),
                },
                "catalog_snapshot": {
                    "downloaded_bytes": db_bytes,
                    "source": "isolated_fly_pilot_sqlite_backup",
                },
                "publication_gate": {
                    "connector_valid_and_explicit_currency": connector_valid,
                    "connector_invalid_or_currency_unproven": connector_invalid,
                    "validation_reasons": dict(sorted(parser_validation.items())),
                    "normalization_errors": dict(sorted(normalization_errors.items())),
                },
                "canonical_database_match": {
                    "matched_records": db_matches,
                    "matched_and_connector_valid": db_matches_valid,
                    "outcomes": dict(sorted(database_reasons.items())),
                },
                "legacy_catalog_fallback": legacy_summary,
                "existing_catalog_overlap": {
                    "active_notino_offer_external_ids": len(active_ids),
                    "feed_ids_already_active": len(external_ids & active_ids),
                    "feed_ids_not_yet_active": len(external_ids - active_ids),
                },
                "safety": {
                    "feed_downloaded_once": True,
                    "catalog_database_snapshot_only": True,
                    "database_writes": 0,
                    "offers_created_or_updated": 0,
                    "staging_rows_created": 0,
                    "publication_rules_changed": 0,
                },
            }
            print("NOTINO_FULL_FEED_AUDIT_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
        finally:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
