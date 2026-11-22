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
                 "ingestion_runs_by_status":[],"offers_by_store":[]}
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
            if "ingestion_raw" in tables:
                out["ingestion_raw_by_status"]=[dict(r) for r in c.execute(text("SELECT status,count(*) AS rows FROM ingestion_raw GROUP BY status ORDER BY status")).mappings()]
            if "ingestion_runs" in tables:
                out["ingestion_runs_by_status"]=[dict(r) for r in c.execute(text("SELECT status,count(*) AS runs,sum(products_discovered) AS discovered,sum(offers_created) AS offers_created,sum(offers_updated) AS offers_updated,sum(offers_rejected) AS offers_rejected FROM ingestion_runs GROUP BY status ORDER BY status")).mappings()]
            print(json.dumps(out,default=str,sort_keys=True))
    finally:
        engine.dispose()
if __name__=="__main__":
    main()
