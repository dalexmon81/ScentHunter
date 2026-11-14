"""Choose a real Notino feed row that survives the public retailer-only guards."""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Callable, Iterable

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def find_publicable_sample(
    candidates: Iterable[tuple[str, str, str]],
    lookup: Callable[[str], list[dict]],
    is_publicable: Callable[[dict], bool],
) -> tuple[str, str, str] | None:
    """Return the first candidate found by public search and accepted by aggregation."""
    for brand, title, external_id in candidates:
        query = f"{brand} {title}"
        for offer in lookup(query):
            if str(offer.get("external_id") or "") != str(external_id):
                continue
            if is_publicable(offer):
                return str(brand), str(title), str(external_id)
            break
    return None


def _load_candidates(database: Path) -> list[tuple[str, str, str]]:
    uri = f"file:{database.resolve()}?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        rows = connection.execute(
            """
            SELECT f.brand, f.title, f.external_id
            FROM notino_feed_listings AS f
            WHERE f.availability = 'in stock'
              AND f.currency = 'EUR'
              AND f.price > 0
              AND f.size_ml >= 30
              AND f.affiliate_url LIKE 'https://%'
              AND (
                    f.gtin IS NULL
                    OR trim(f.gtin) = ''
                    OR NOT EXISTS (
                        SELECT 1 FROM product_variants AS v
                        WHERE v.gtin = f.gtin
                    )
              )
              AND NOT EXISTS (
                    SELECT 1
                    FROM offers AS o
                    JOIN stores AS s ON s.id = o.store_id
                    WHERE s.slug = 'notino-fr'
                      AND o.external_product_id = f.external_id
              )
            ORDER BY f.price, f.external_id
            LIMIT 500
            """
        ).fetchall()
    return [(str(brand), str(title), str(external_id)) for brand, title, external_id in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    if not args.database.is_file():
        raise FileNotFoundError(f"staging database not found: {args.database}")

    from app.services.notino_phase2_search import search_notino_retailer_listings
    from main import _aggregate_identity_results

    candidates = _load_candidates(args.database)

    def lookup(query: str) -> list[dict]:
        return search_notino_retailer_listings(query, set(), limit=100)

    def is_publicable(offer: dict) -> bool:
        groups, unresolved = _aggregate_identity_results([offer])
        return (
            not unresolved
            and len(groups) == 1
            and groups[0].get("retailer_only") is True
            and groups[0].get("catalog_id") == offer.get("catalog_id")
            and len(groups[0].get("offers") or []) == 1
        )

    sample = find_publicable_sample(candidates, lookup, is_publicable)
    if sample is None:
        raise SystemExit(
            "No in-stock, unmapped Notino feed listing among the first "
            f"{len(candidates)} candidates survives the production public aggregation guards."
        )
    print(json.dumps(list(sample), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
