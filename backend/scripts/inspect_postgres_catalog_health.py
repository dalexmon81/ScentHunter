"""Read-only health snapshot for the canonical PostgreSQL fragrance catalog."""
from __future__ import annotations
import json, os
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url

def main():
    raw=os.environ.get("SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL","").strip()
    if not raw:
        raise RuntimeError("SCENTHUNTER_MIGRATION_TARGET_DATABASE_URL is required")
    url=make_url(raw)
    if url.drivername=="postgresql":
        url=url.set(drivername="postgresql+psycopg")
    if url.drivername!="postgresql+psycopg":
        raise RuntimeError("Expected PostgreSQL target")
    engine=create_engine(url,pool_pre_ping=True,pool_size=1,max_overflow=0)
    try:
        with engine.connect() as c:
            tables=set(inspect(c).get_table_names())
            out={"database":c.execute(text("select current_database()")).scalar_one(),
                 "tables_present":sorted(tables),
                 "counts":{},"offers_by_status":[],"ingestion_raw_by_status":[],
                 "ingestion_runs_by_status":[],"offers_by_store":[],"raw_by_store_status":[],"queue_failures_by_error":[],"queue_by_store_stage_status":[],"recent_problem_runs":[],"ingestion_error_counts":[],"raw_identity_gaps":[]}
            for table in ("brands","fragrances","product_variants","stores","offers","price_history","match_audit","ingestion_raw","ingestion_runs","ingestion_queue_jobs"):
                if table in tables:
                    out["counts"][table]=c.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
            if "offers" in tables:
                out["offers_by_status"]=[dict(r) for r in c.execute(text("SELECT status,count(*) AS jobs FROM offers GROUP BY status ORDER BY status")).mappings()]
                out["offers_by_store"]=[dict(r) for r in c.execute(text("""
                    SELECT s.slug,s.name,count(o.id) AS offers,
                           count(o.id) FILTER (WHERE o.status='active') AS active_offers,
                           max(o.captured_at) AS latest_capture
                    FROM stores s LEFT JOIN offers o ON o.store_id=s.id
                    GROUP BY s.slug,s.name ORDER BY s.slug
                """)).mappings()]
                out["ingestion_error_counts"]=[dict(r) for r in c.execute(text("""
                    SELECT s.slug, err.message AS error, count(*) AS runs
                    FROM ingestion_runs r JOIN stores s ON s.id=r.store_id
                    CROSS JOIN LATERAL json_array_elements_text(COALESCE(r.errors, '[]'::json)) AS err(message)
                    WHERE r.status IN ('partial','failed')
                    GROUP BY s.slug, err.message ORDER BY runs DESC LIMIT 40
                """)).mappings()]
            if "ingestion_raw" in tables:
                out["ingestion_raw_by_status"]=[dict(r) for r in c.execute(text("SELECT status,count(*) AS rows FROM ingestion_raw GROUP BY status ORDER BY status")).mappings()]
            if "ingestion_runs" in tables:
                out["ingestion_runs_by_status"]=[dict(r) for r in c.execute(text("SELECT status,count(*) AS runs,sum(products_discovered) AS discovered,sum(offers_created) AS offers_created,sum(offers_updated) AS offers_updated,sum(offers_rejected) AS offers_rejected FROM ingestion_runs GROUP BY status ORDER BY status")).mappings()]
                out["recent_problem_runs"]=[dict(r) for r in c.execute(text("""
                    SELECT s.slug, r.status, r.products_discovered, r.offers_created,
                           r.offers_updated, r.offers_rejected, r.errors, r.started_at, r.finished_at
                    FROM ingestion_runs r JOIN stores s ON s.id=r.store_id
                    WHERE r.status IN ('partial','failed')
                    ORDER BY r.started_at DESC LIMIT 20
                """)).mappings()]
            if "ingestion_raw" in tables:
                out["raw_by_store_status"]=[dict(r) for r in c.execute(text("""
                    SELECT s.slug, ir.status, count(*) AS rows
                    FROM ingestion_raw ir JOIN stores s ON s.id=ir.store_id
                    GROUP BY s.slug, ir.status ORDER BY s.slug, ir.status
                """)).mappings()]
                out["raw_identity_gaps"]=[dict(r) for r in c.execute(text("""
                    SELECT s.slug, ir.status, count(*) AS rows,
                           count(*) FILTER (WHERE NULLIF(ir.raw_payload->>'brand', '') IS NULL) AS missing_brand,
                           count(*) FILTER (WHERE NULLIF(ir.raw_payload->>'title', '') IS NULL) AS missing_title,
                           count(*) FILTER (WHERE NULLIF(ir.raw_payload->>'size_ml', '') IS NULL) AS missing_size_ml,
                           count(*) FILTER (WHERE NULLIF(ir.raw_payload->>'concentration', '') IS NULL) AS missing_concentration,
                           count(*) FILTER (WHERE NULLIF(ir.raw_payload->>'size_ml', '') IS NULL
                               AND COALESCE(ir.raw_payload->>'title', '') ~* '[0-9]+([.,][0-9]+)?\\s*ml') AS size_only_in_title
                    FROM ingestion_raw ir JOIN stores s ON s.id=ir.store_id
                    GROUP BY s.slug, ir.status ORDER BY s.slug, ir.status
                """)).mappings()]
            if "ingestion_queue_jobs" in tables:
                out["queue_by_store_stage_status"]=[dict(r) for r in c.execute(text("""
                    SELECT coalesce(s.slug,'<unknown-store>') AS store_slug,
                           q.stage,q.status,count(*) AS jobs,
                           min(q.created_at) AS oldest_created,
                           max(q.created_at) AS newest_created
                    FROM ingestion_queue_jobs q
                    LEFT JOIN stores s ON s.id::text=q.payload->>'store_id'
                    GROUP BY coalesce(s.slug,'<unknown-store>'),q.stage,q.status
                    ORDER BY store_slug,q.stage,q.status
                """)).mappings()]
                out["queue_failures_by_error"]=[dict(r) for r in c.execute(text("""
                    SELECT stage, left(coalesce(last_error,'<no error>'),240) AS error, count(*) AS jobs
                    FROM ingestion_queue_jobs WHERE status='failed'
                    GROUP BY stage, left(coalesce(last_error,'<no error>'),240)
                    ORDER BY jobs DESC LIMIT 20
                """)).mappings()]
            print(json.dumps(out,default=str,sort_keys=True))
    finally:
        engine.dispose()
if __name__=="__main__":
    main()
