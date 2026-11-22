"""Read-only forensic report for PostgreSQL ingestion rows and run counters.

This script never changes database state. It deliberately reports run counters
separately from ingestion_raw row statuses: offers_rejected is a worker counter,
not a count of rows whose status is 'rejected'.
"""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url



def _runtime_call_sites() -> list[dict]:
    """Read deployed Python source and report identity/matcher call sites without importing it."""
    root = Path("/app/backend")
    targets = (
        "app/services/canonical_matching.py",
        "app/services/connector_ingestion.py",
        "app/services/bplatz_phase2_adapter.py",
        "app/workers/legacy_runtime.py",
        "app/workers/notino_runtime.py",
        "app/workers/tasks.py",
    )
    found = []
    for relative in targets:
        path = root / relative
        if not path.is_file():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            found.append({"file": relative, "parse_error": str(exc)})
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else (
                node.func.attr if isinstance(node.func, ast.Attribute) else ""
            )
            if name in {"resolve_canonical_variant", "persist_connector_record", "_is_unique_canonical_candidate"}:
                found.append({
                    "file": relative,
                    "line": getattr(node, "lineno", None),
                    "call": ast.unparse(node),
                })
    return found


def main() -> None:
    raw = os.environ.get("SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL", "").strip()
    if not raw:
        raise RuntimeError("SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL is required")
    url = make_url(raw)
    if url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise RuntimeError("Expected PostgreSQL target using psycopg 3")

    engine = create_engine(url, pool_pre_ping=True, pool_size=1, max_overflow=0)
    try:
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            required = {"stores", "ingestion_raw", "ingestion_runs"}
            missing = sorted(required - tables)
            if missing:
                raise RuntimeError(f"Required PostgreSQL tables are missing: {missing}")

            report = {
                "database": connection.execute(text("SELECT current_database()")).scalar_one(),
                "read_only": True,
                "interpretation": {
                    "offers_rejected": "ingestion_runs counter; not equivalent to ingestion_raw.status='rejected'",
                    "ingestion_raw_status": "row lifecycle state; pending/matched/promoted/rejected are distinct",
                },
                "counts": {},
                "raw_by_store_status": [],
                "raw_reason_by_store": [],
                "raw_identity_gaps_by_store_status": [],
                "sample_problem_rows": [],
                "run_counters_by_store_status": [],
                "run_error_reasons_by_store": [],
                "recent_problem_runs": [],
                "queue_by_store_stage_status": [],
                "offers_by_store_status": [],
                "deployed_runtime_call_sites": _runtime_call_sites(),
            }

            for table in ("brands", "fragrances", "product_variants", "stores",
                          "offers", "price_history", "match_audit",
                          "ingestion_raw", "ingestion_runs", "ingestion_queue_jobs"):
                if table in tables:
                    report["counts"][table] = connection.execute(
                        text(f'SELECT count(*) FROM "{table}"')
                    ).scalar_one()

            report["raw_by_store_status"] = [
                dict(row) for row in connection.execute(text("""
                    SELECT s.slug AS store, ir.status, count(*) AS records
                    FROM ingestion_raw ir JOIN stores s ON s.id=ir.store_id
                    GROUP BY s.slug, ir.status ORDER BY s.slug, ir.status
                """)).mappings()
            ]

            report["raw_reason_by_store"] = [
                dict(row) for row in connection.execute(text("""
                    SELECT s.slug AS store, ir.status,
                           coalesce(nullif(ir.rejection_reason,''), '<no reason recorded>') AS reason,
                           coalesce(nullif(ir.match_method,''), '<no match method>') AS match_method,
                           count(*) AS records
                    FROM ingestion_raw ir JOIN stores s ON s.id=ir.store_id
                    GROUP BY s.slug, ir.status, ir.rejection_reason, ir.match_method
                    ORDER BY records DESC, s.slug, ir.status LIMIT 200
                """)).mappings()
            ]

            report["raw_identity_gaps_by_store_status"] = [
                dict(row) for row in connection.execute(text("""
                    SELECT s.slug AS store, ir.status, count(*) AS records,
                           count(*) FILTER (WHERE coalesce(ir.raw_payload->>'brand', ir.raw_payload->>'brand_raw') IS NULL) AS missing_brand,
                           count(*) FILTER (WHERE coalesce(ir.raw_payload->>'title', ir.raw_payload->>'name', ir.raw_payload->>'raw_name') IS NULL) AS missing_name,
                           count(*) FILTER (WHERE coalesce(ir.raw_payload->>'size_ml', ir.raw_payload->'attributes'->>'size_ml') IS NULL) AS missing_size,
                           count(*) FILTER (WHERE coalesce(ir.raw_payload->>'concentration', ir.raw_payload->'attributes'->>'concentration') IS NULL) AS missing_concentration,
                           count(*) FILTER (WHERE coalesce(ir.raw_payload->>'price', ir.raw_payload->'offer'->>'price', ir.raw_payload->>'price_num') IS NULL) AS missing_price,
                           count(*) FILTER (WHERE coalesce(ir.raw_payload->>'availability', ir.raw_payload->'offer'->>'availability', ir.raw_payload->>'available') IS NULL) AS missing_availability,
                           count(*) FILTER (WHERE coalesce(ir.raw_payload->>'product_url', ir.raw_payload->>'url') IS NULL) AS missing_url,
                           count(*) FILTER (WHERE coalesce(ir.raw_payload->>'size_ml', ir.raw_payload->'attributes'->>'size_ml') IS NULL
                               AND coalesce(ir.raw_payload->>'title', ir.raw_payload->>'name', '') ~* '[0-9]+([.,][0-9]+)?[[:space:]]*ml') AS size_present_only_in_title
                    FROM ingestion_raw ir JOIN stores s ON s.id=ir.store_id
                    GROUP BY s.slug, ir.status ORDER BY s.slug, ir.status
                """)).mappings()
            ]

            report["sample_problem_rows"] = [
                dict(row) for row in connection.execute(text("""
                    SELECT s.slug AS store, ir.id::text AS ingestion_raw_id,
                           ir.status, ir.external_product_id, ir.match_method,
                           ir.match_confidence, ir.rejection_reason,
                           ir.raw_payload
                    FROM ingestion_raw ir JOIN stores s ON s.id=ir.store_id
                    WHERE ir.status IN ('rejected','unmatched','pending','matched')
                    ORDER BY CASE ir.status WHEN 'rejected' THEN 0 WHEN 'unmatched' THEN 1
                             WHEN 'matched' THEN 2 ELSE 3 END,
                             ir.created_at DESC
                    LIMIT 60
                """)).mappings()
            ]

            report["run_counters_by_store_status"] = [
                dict(row) for row in connection.execute(text("""
                    SELECT s.slug AS store, r.status, count(*) AS runs,
                           sum(r.products_discovered) AS discovered,
                           sum(r.offers_created) AS offers_created,
                           sum(r.offers_updated) AS offers_updated,
                           sum(r.offers_rejected) AS offers_rejected,
                           sum(r.offers_rejected) - count(*) FILTER (WHERE r.status='partial') AS rejected_counter_minus_partial_runs
                    FROM ingestion_runs r JOIN stores s ON s.id=r.store_id
                    GROUP BY s.slug, r.status ORDER BY s.slug, r.status
                """)).mappings()
            ]

            report["run_error_reasons_by_store"] = [
                dict(row) for row in connection.execute(text("""
                    SELECT s.slug AS store, err.message AS error, count(*) AS runs
                    FROM ingestion_runs r JOIN stores s ON s.id=r.store_id
                    CROSS JOIN LATERAL json_array_elements_text(COALESCE(r.errors, '[]'::json)) AS err(message)
                    WHERE r.status IN ('partial','failed')
                    GROUP BY s.slug, err.message ORDER BY runs DESC LIMIT 100
                """)).mappings()
            ]

            report["recent_problem_runs"] = [
                dict(row) for row in connection.execute(text("""
                    SELECT s.slug AS store, r.id::text AS run_id, r.status,
                           r.products_discovered, r.offers_created, r.offers_updated,
                           r.offers_rejected, r.errors, r.started_at, r.finished_at
                    FROM ingestion_runs r JOIN stores s ON s.id=r.store_id
                    WHERE r.status IN ('partial','failed')
                    ORDER BY r.started_at DESC LIMIT 50
                """)).mappings()
            ]

            if "ingestion_queue_jobs" in tables:
                report["queue_by_store_stage_status"] = [
                    dict(row) for row in connection.execute(text("""
                        SELECT coalesce(s.slug,'<unknown-store>') AS store,
                               q.stage, q.status, count(*) AS jobs,
                               min(q.created_at) AS oldest_created,
                               max(q.created_at) AS newest_created
                        FROM ingestion_queue_jobs q
                        LEFT JOIN stores s ON s.id::text=q.payload->>'store_id'
                        GROUP BY coalesce(s.slug,'<unknown-store>'),q.stage,q.status
                        ORDER BY store,q.stage,q.status
                    """)).mappings()
                ]
            if "offers" in tables:
                report["offers_by_store_status"] = [
                    dict(row) for row in connection.execute(text("""
                        SELECT s.slug AS store, o.status, count(*) AS offers,
                               max(o.captured_at) AS latest_capture
                        FROM offers o JOIN stores s ON s.id=o.store_id
                        GROUP BY s.slug,o.status ORDER BY s.slug,o.status
                    """)).mappings()
                ]

            print(json.dumps(report, default=str, sort_keys=True))
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
