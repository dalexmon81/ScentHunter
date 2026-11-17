"""Persist one freshly verified Bplatz Liquid Brun 100 ml observation."""
from __future__ import annotations

import argparse
import base64
import json
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.db import make_engine  # noqa: E402
from app.models import (  # noqa: E402
    IngestionRaw, MatchAudit, Offer, PriceHistory, Store,
)
from app.services.bplatz_phase2_adapter import persist_bplatz_record  # noqa: E402
from scenthunter_next_engine.next_engine_service import NextEngineService  # noqa: E402
from scenthunter_next_engine.offer_normalizer import normalize_offer  # noqa: E402


PRODUCT_URL_PATH = "/products/fragrance-world-liquid-brun-eau-de-parfum-100ml"
CANONICAL_PRODUCT_ID = "SH-0030"
CANONICAL_VARIANT_ID = "VAR-f87146c82d167f4c"
SCHEMA_REVISION = "0016_product_identifiers"
TABLES = (
    "brands", "fragrances", "ingestion_raw", "ingestion_runs",
    "legacy_product_id_map", "legacy_variant_id_map", "match_audit",
    "offers", "price_history", "product_variants", "stores", "product_identifiers",
)


def _validate_report(report: dict, *, now: datetime) -> tuple[dict, Decimal]:
    if report.get("status") != "verified" or report.get("database_written") is not False:
        raise ValueError("input must be a successful read-only live-check report")
    if (
        report.get("store") != "Bplatz"
        or report.get("brand") != "French Avenue"
        or report.get("product") != "Liquid Brun"
        or report.get("size_ml") != 100
        or report.get("canonical_product_id") != CANONICAL_PRODUCT_ID
        or report.get("canonical_variant_id") != CANONICAL_VARIANT_ID
        or report.get("currency") != "EUR"
        or report.get("availability") != "in_stock"
    ):
        raise ValueError("live report does not match the authorized Liquid Brun pilot")

    captured_at = datetime.fromisoformat(str(report["captured_at"]))
    if captured_at.tzinfo is None:
        raise ValueError("live report timestamp must include a timezone")
    age = now.astimezone(timezone.utc) - captured_at.astimezone(timezone.utc)
    if age < timedelta(0) or age > timedelta(hours=1):
        raise ValueError("live report is outside the one-hour persistence window")

    raw_record = report.get("raw_record")
    if not isinstance(raw_record, dict) or raw_record.get("currency_explicit") is not True:
        raise ValueError("live report is missing explicit-currency source evidence")
    if raw_record.get("product_url") != report.get("url"):
        raise ValueError("live report URL does not match its parsed raw record")
    parsed_url = urlsplit(str(report.get("url") or ""))
    host = (parsed_url.hostname or "").lower().rstrip(".")
    if (
        parsed_url.scheme != "https"
        or (host != "bplatz.de" and not host.endswith(".bplatz.de"))
        or parsed_url.path != PRODUCT_URL_PATH
        or parsed_url.username is not None
        or parsed_url.password is not None
    ):
        raise ValueError("live report URL is outside the exact Bplatz pilot product")

    try:
        price = Decimal(str(report["price"]))
    except (InvalidOperation, KeyError) as exc:
        raise ValueError("live report price is invalid") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError("live report price must be positive and finite")

    record = dict(raw_record)
    record["captured_at"] = captured_at.astimezone(timezone.utc).isoformat()
    return record, price


def _readonly_connection(path: Path) -> sqlite3.Connection:
    uri = path.resolve().as_uri() + "?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _database_snapshot(path: Path) -> dict:
    with closing(_readonly_connection(path)) as connection:
        tables = {
            row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        missing = (set(TABLES) | {"alembic_version"}) - tables
        if missing:
            raise RuntimeError(f"Phase 2 schema is incomplete: {sorted(missing)}")
        revision = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        if revision is None or revision[0] != SCHEMA_REVISION:
            raise RuntimeError("Phase 2 schema revision is not the expected pilot revision")
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in TABLES
        }
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok" or foreign_key_errors:
        raise RuntimeError("Phase 2 database integrity or foreign-key check failed")
    return {
        "revision": revision[0],
        "counts": counts,
        "integrity_check": integrity,
        "foreign_key_errors": len(foreign_key_errors),
    }


def _backup_database(source: Path, backup_dir: Path, run_id: str) -> tuple[Path, dict]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"phase2-pre-liquid-brun-{run_id}.sqlite3"
    if backup.exists():
        raise FileExistsError(f"refusing to overwrite existing backup: {backup}")
    with closing(_readonly_connection(source)) as source_connection:
        with closing(sqlite3.connect(backup, timeout=30)) as backup_connection:
            source_connection.backup(backup_connection)
    verified = _database_snapshot(backup)
    if backup.stat().st_size <= 0:
        raise RuntimeError("verified Phase 2 backup is empty")
    return backup, verified


def persist_report(
    report: dict, *, run_id: str, backup_dir: Path,
    engine=None, now: datetime | None = None,
) -> dict:
    if not isinstance(report, dict):
        raise TypeError("live report must be a JSON object")
    if not run_id.isdecimal():
        raise ValueError("workflow run id must contain only decimal digits")
    now = now or datetime.now(timezone.utc)
    raw_record, expected_price = _validate_report(report, now=now)

    owns_engine = engine is None
    engine = engine or make_engine()
    try:
        url = make_url(str(engine.url))
        if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
            raise RuntimeError("pilot persistence requires the provisioned SQLite Phase 2 database")
        database_path = Path(url.database).expanduser().resolve()
        if not database_path.is_file():
            raise FileNotFoundError("provisioned Phase 2 SQLite database does not exist")

        before = _database_snapshot(database_path)
        with closing(_readonly_connection(database_path)) as connection:
            store_rows = connection.execute(
                "SELECT id, domain, status, offer_ttl_minutes FROM stores WHERE slug='bplatz'"
            ).fetchall()
            if (
                len(store_rows) != 1
                or store_rows[0][1] != "bplatz.de"
                or store_rows[0][2] != "active"
                or not isinstance(store_rows[0][3], int)
                or store_rows[0][3] <= 0
            ):
                raise RuntimeError("Bplatz store is not uniquely configured, active and freshness-bounded")
            variant_rows = connection.execute(
                "SELECT product_variant_id FROM legacy_variant_id_map "
                "WHERE legacy_variant_id=?",
                (CANONICAL_VARIANT_ID,),
            ).fetchall()
            if len(variant_rows) != 1:
                raise RuntimeError("Liquid Brun canonical variant mapping is missing or ambiguous")
            existing_offer_count = connection.execute(
                "SELECT COUNT(*) FROM offers WHERE store_id=? AND product_variant_id=?",
                (store_rows[0][0], variant_rows[0][0]),
            ).fetchone()[0]
            if existing_offer_count > 1:
                raise RuntimeError("multiple Bplatz offers exist for the pilot variant; refusing update")

        backup, backup_snapshot = _backup_database(database_path, backup_dir, run_id)
        if backup_snapshot["revision"] != before["revision"] or backup_snapshot["counts"] != before["counts"]:
            raise RuntimeError("Phase 2 database changed while its pre-write backup was being verified")

        matcher = NextEngineService.from_catalog_file(BACKEND / "product_catalog.json")
        normalized = normalize_offer(raw_record, retailer="Bplatz", currency_default="EUR")
        matched = matcher.process_offers([normalized])
        if (
            matched.matched_offer_count != 1
            or len(matched.groups) != 1
            or matched.groups[0].canonical_product_id != CANONICAL_PRODUCT_ID
            or matched.groups[0].canonical_variant_id != CANONICAL_VARIANT_ID
        ):
            raise RuntimeError("live record did not match exactly the approved canonical variant")

        with Session(engine) as session, session.begin():
            store = session.scalar(select(Store).where(Store.slug == "bplatz"))
            if store is None or store.status != "active" or store.domain != "bplatz.de":
                raise RuntimeError("Bplatz store configuration changed after preflight")
            result = persist_bplatz_record(
                session, store_id=store.id, raw_record=raw_record, matcher=matcher,
            )
            if result.status != "promoted" or result.offer_id is None:
                raise RuntimeError(f"live pilot record was not promoted: {result.reason or result.status}")
            canonical_variant_uuid = UUID(variant_rows[0][0])
            if result.product_variant_id != canonical_variant_uuid:
                raise RuntimeError("database matcher resolved a different canonical variant")

            offer = session.get(Offer, result.offer_id)
            raw = session.get(IngestionRaw, result.ingestion_raw_id)
            history_count = session.scalar(select(func.count()).select_from(PriceHistory))
            audit_count = session.scalar(select(func.count()).select_from(MatchAudit))
            if (
                offer is None or raw is None
                or offer.store_id != store.id
                or offer.product_variant_id != result.product_variant_id
                or offer.price != expected_price
                or offer.currency != "EUR"
                or offer.availability != "in_stock"
                or offer.status != "active"
                or offer.valid_until is None
                or offer.valid_until <= offer.captured_at
                or raw.status != "promoted"
                or raw.product_variant_id != result.product_variant_id
                or raw.raw_payload.get("currency_explicit") is not True
                or not history_count or not audit_count
            ):
                raise RuntimeError("persisted pilot offer failed its publication-contract checks")
            expected_capture = datetime.fromisoformat(raw_record["captured_at"])
            actual_capture = offer.captured_at
            if actual_capture.tzinfo is None:
                actual_capture = actual_capture.replace(tzinfo=timezone.utc)
            if actual_capture.astimezone(timezone.utc) != expected_capture.astimezone(timezone.utc):
                raise RuntimeError("persisted pilot capture time differs from source evidence")
            session.flush()

            expected_counts = dict(before["counts"])
            expected_counts["ingestion_raw"] += 1
            expected_counts["match_audit"] += 1
            expected_counts["price_history"] += 1
            expected_counts["offers"] += int(existing_offer_count == 0)
            model_by_table = {
                "ingestion_raw": IngestionRaw,
                "match_audit": MatchAudit,
                "offers": Offer,
                "price_history": PriceHistory,
            }
            for table, model in model_by_table.items():
                count = session.scalar(select(func.count()).select_from(model))
                if count != expected_counts[table]:
                    raise RuntimeError(f"unexpected {table} row-count change during pilot persistence")
            for table, expected in expected_counts.items():
                if table in model_by_table:
                    continue
                actual = session.connection().exec_driver_sql(
                    f"SELECT COUNT(*) FROM {table}"
                ).scalar_one()
                if actual != expected:
                    raise RuntimeError(f"unexpected {table} row-count change during pilot persistence")

            offer_id = str(result.offer_id)
            raw_id = str(result.ingestion_raw_id)
            captured_at = offer.captured_at
            persisted_offer = {
                "id": offer_id,
                "price": str(offer.price),
                "currency": offer.currency,
                "availability": offer.availability,
                "url": offer.url,
                "captured_at": captured_at.isoformat(),
            }

        after = _database_snapshot(database_path)
        if after["counts"] != expected_counts:
            raise RuntimeError("Phase 2 post-write counts differ from the single-offer write contract")
        return {
            "status": "persisted",
            "database": str(database_path),
            "backup": str(backup),
            "backup_verified": True,
            "revision": after["revision"],
            "before_counts": before["counts"],
            "after_counts": after["counts"],
            "offer": persisted_offer,
            "ingestion_raw_id": raw_id,
            "canonical_product_id": CANONICAL_PRODUCT_ID,
            "canonical_variant_id": CANONICAL_VARIANT_ID,
            "legacy_database_touched": False,
            "persistent_feature_flag_changed": False,
        }
    finally:
        if owns_engine:
            engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--payload-base64", required=True)
    args = parser.parse_args()
    try:
        report = json.loads(base64.b64decode(args.payload_base64, validate=True))
        result = persist_report(
            report,
            run_id=args.run_id,
            backup_dir=Path("/data/backups"),
        )
    except (
        OSError, RuntimeError, TypeError, ValueError, KeyError, IndexError,
        sqlite3.Error, SQLAlchemyError, json.JSONDecodeError,
    ) as exc:
        print(json.dumps({"status": "failed", "reason": str(exc)}, ensure_ascii=False), flush=True)
        return 1
    print("PHASE2_LIQUID_BRUN_LIVE_PERSIST=" + json.dumps(result, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
