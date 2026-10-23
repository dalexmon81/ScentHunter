"""Bounded live retailer parser probe; public requests only, no database access."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.scrapers.deloox import scraper as deloox
from backend.scrapers.parfumzentrum import scraper as parfumzentrum

QUERY = "Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml"
REPORT = Path("live-retailer-parser-probe.json")


def probe(module):
    started = time.monotonic()
    try:
        rows = module.search(QUERY) or []
        clean_rows = []
        for row in rows[:5]:
            if not isinstance(row, dict):
                continue
            attributes = row.get("attributes") or {}
            size = attributes.get("size_ml") or {}
            offer = row.get("offer") or {}
            identity = row.get("identity") or {}
            gtin = identity.get("gtin") or {}
            clean_rows.append({
                "name": row.get("name") or row.get("title"),
                "url": row.get("url") or row.get("product_url"),
                "size_ml": row.get("size_ml", size.get("value") if isinstance(size, dict) else None),
                "concentration": row.get("concentration") or (attributes.get("concentration") or {}).get("value"),
                "price": offer.get("price", row.get("price_num", row.get("price"))),
                "availability": offer.get("availability", row.get("availability")),
                "gtin": gtin.get("value") if isinstance(gtin, dict) else row.get("gtin"),
            })
        return {"status": "results" if clean_rows else "zero_results", "rows": clean_rows,
                "row_count": len(rows), "elapsed_seconds": round(time.monotonic() - started, 2)}
    except Exception as exc:
        return {"status": "error", "error": type(exc).__name__ + ": " + str(exc)[:240],
                "elapsed_seconds": round(time.monotonic() - started, 2)}


def main():
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "query": QUERY,
        "scope": "Public retailer scraper search only. No production database, catalog writes, or deployment.",
        "deloox": probe(deloox),
        "parfumzentrum": probe(parfumzentrum),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
