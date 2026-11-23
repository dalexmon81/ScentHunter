"""Read-only diagnosis of legacy catalog URLs missing from PostgreSQL fetch queue."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

from sqlalchemy import MetaData, Table, bindparam, select, text

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
SEED_PATH = ROOT / "backend/scripts/seed_postgres_fetch_queue_from_legacy_catalog.py"
SPEC = importlib.util.spec_from_file_location("seed_postgres_fetch_queue", SEED_PATH)
SEED = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SEED)


def main() -> None:
    source = SEED.source_engine(Path("/data/store_catalog.sqlite3"))
    target = SEED.target_engine()
    try:
        with source.connect() as src:
            with src.begin():
                candidates, rejected, duplicates, rejected_domains = SEED._read_candidates(src)

        report = {
            "mode": "read_only_diagnosis",
            "candidate_count": len(candidates),
            "rejected_by_store": rejected,
            "duplicate_candidates": duplicates,
            "missing_candidates": [],
            "candidate_status_counts": {},
            "stores_missing": [],
        }
        with target.connect() as conn:
            report["target_database"] = conn.execute(
                text("SELECT current_database()")
            ).scalar_one()
            if report["target_database"] != "scenthunter_offerfirst":
                raise RuntimeError("Unexpected target database")
            queue = Table("ingestion_queue_jobs", MetaData(), autoload_with=conn)
            stores = Table("stores", MetaData(), autoload_with=conn)
            slugs = [item[0] for item in SEED.STORE_CONFIG.values()]
            store_ids = dict(conn.execute(
                select(stores.c.slug, stores.c.id).where(stores.c.slug.in_(slugs))
            ).all())

            keys = {}
            for store_key, url in candidates:
                slug = SEED.STORE_CONFIG[store_key][0]
                store_id = store_ids.get(slug)
                if store_id is None:
                    report["stores_missing"].append(slug)
                    report["missing_candidates"].append({
                        "store": slug,
                        "url": url,
                        "reason": "store_row_missing",
                    })
                    continue
                payload = {
                    "store_id": str(store_id),
                    "external_product_id": url,
                }
                raw = json.dumps(
                    payload, sort_keys=True, separators=(",", ":"), allow_nan=False
                )
                digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                keys[digest] = (slug, url)

            # Keep each SELECT below PostgreSQL's 65,535 bind-parameter limit.
            # This is a read-only lookup; batching does not alter queue rows.
            statuses = {}
            key_list = list(keys)
            batch_size = 5000
            for offset in range(0, len(key_list), batch_size):
                batch_keys = key_list[offset:offset + batch_size]
                rows = conn.execute(
                    select(queue.c.dedupe_key, queue.c.status).where(
                        queue.c.stage == "fetch",
                        queue.c.dedupe_key.in_(batch_keys),
                    )
                ).all()
                for digest, status in rows:
                    statuses.setdefault(digest, []).append(status)

            for digest, (slug, url) in keys.items():
                found = statuses.get(digest, [])
                if not found:
                    report["missing_candidates"].append({
                        "store": slug,
                        "url": url,
                        "dedupe_key": digest,
                        "reason": "no_matching_queue_row",
                    })
                else:
                    for status in found:
                        report["candidate_status_counts"][status] = (
                            report["candidate_status_counts"].get(status, 0) + 1
                        )

            report["matching_queue_rows"] = sum(len(v) for v in statuses.values())
            report["missing_count"] = len(report["missing_candidates"])
            report["stores_missing"] = sorted(set(report["stores_missing"]))
            print(json.dumps(report, sort_keys=True, indent=2))
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    main()
