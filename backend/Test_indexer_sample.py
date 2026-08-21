"""
ScentHunter - real sample test for STEP 3.

Runs the existing indexer against a small slice of the real canonical
catalog and the real scraper modules.

No product names are hard-coded: the sample is taken from the first N
catalog entries at runtime.

Usage from backend/:
    python test_indexer_sample.py --limit 1
    python test_indexer_sample.py --limit 3
    python test_indexer_sample.py --limit 1 --stores bplatz deloox
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from indexer import (
    CATALOG_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_STORES,
    load_catalog,
    refresh,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test reale STEP 3 ScentHunter"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=1,
        help="Numero di prodotti canonici da testare",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Posizione iniziale nel catalogo",
    )
    parser.add_argument(
        "--stores",
        nargs="+",
        default=list(DEFAULT_STORES),
        help="Scraper reali da testare",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Numero massimo di lavori concorrenti",
    )
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Database SQLite di test",
    )

    args = parser.parse_args()

    catalog = load_catalog(Path(CATALOG_PATH))
    sample = catalog[
        max(0, args.offset):
        max(0, args.offset) + max(1, args.limit)
    ]

    if not sample:
        raise SystemExit("Campione catalogo vuoto.")

    print("=" * 70)
    print("SCENTHUNTER - TEST REALE STEP 3")
    print("=" * 70)
    print(f"Prodotti nel catalogo: {len(catalog)}")
    print(f"Campione: {len(sample)}")
    print(f"Offset: {max(0, args.offset)}")
    print(f"Store: {', '.join(args.stores)}")
    print(f"Workers: {max(1, args.workers)}")
    print()

    print("Prodotti scelti dal catalogo:")
    for item in sample:
        print(
            f"  - {item['product_id']} | "
            f"{item.get('brand_name', '')} - "
            f"{item.get('family_name', '')}"
        )

    print()
    print("Avvio scraper reali...")
    started = time.perf_counter()

    stats = refresh(
        catalog_path=CATALOG_PATH,
        db_path=args.db,
        stores=args.stores,
        workers=max(1, args.workers),
        offset=max(0, args.offset),
        limit=max(1, args.limit),
    )

    elapsed = round(time.perf_counter() - started, 2)

    print()
    print("=" * 70)
    print("RISULTATO")
    print("=" * 70)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print()
    print(f"Tempo totale: {elapsed} secondi")

    if stats.get("errors"):
        print()
        print("ERRORI:")
        for key, error in stats["errors"].items():
            print(f"  {key}: {error}")

    print()
    print(
        "OFFERS SCRITTE:",
        stats.get("offers_written", 0),
    )

    print(
        "JOB COMPLETATI:",
        f"{stats.get('completed_jobs', 0)}/{stats.get('jobs', 0)}",
    )

    print(
        "INDICE:",
        json.dumps(
            stats.get("index", {}),
            ensure_ascii=False,
        ),
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
