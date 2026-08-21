"""
ScentHunter - Indexer
STEP 3: populate/update the local ProductIndex from the existing canonical
catalog and the real scraper modules.

Design goals:
- generic: no product/store-specific seeds or exceptions;
- never runs as part of the user's live /search request;
- uses the canonical product catalog as the list of products to refresh;
- runs store refresh jobs concurrently with a bounded worker pool;
- routes scraper output through the existing central discovery/validation layer;
- attaches the canonical product_id before writing offers;
- keeps the local index usable even when one store fails;
- supports partial runs through --limit / --offset / --stores;
- writes only to the local SQLite index.

This is an offline/background updater. It is intentionally separate from main.py.
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


BASE_DIR = Path(__file__).resolve().parent
CATALOG_PATH = BASE_DIR / "product_catalog.json"
DEFAULT_DB_PATH = BASE_DIR / "scenthunter_index.db"

DEFAULT_STORES = (
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "notino",
)

DEFAULT_WORKERS = 8


from product_index import ProductIndex


def load_catalog(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    products = data.get("products", [])

    output: List[Dict[str, Any]] = []

    for item in products:
        if not isinstance(item, dict):
            continue

        product_id = str(item.get("product_id") or "").strip()
        brand = str(item.get("brand_name") or "").strip()
        family = str(item.get("family_name") or "").strip()

        if not product_id or not family:
            continue

        output.append(
            {
                "product_id": product_id,
                "catalog_id": product_id,
                "brand_id": str(item.get("brand_id") or "").strip(),
                "brand": brand,
                "brand_name": brand,
                "name": family,
                "family_name": family,
                "concentration": str(
                    item.get("concentration") or ""
                ).strip(),
                "gender": item.get("gender"),
                "aliases": [
                    str(value).strip()
                    for value in (item.get("aliases") or [])
                    if str(value).strip()
                ],
            }
        )

    return output


def canonical_query(product: Dict[str, Any]) -> str:
    """
    Generic query for a canonical catalog product.

    Brand + family is preferred because it reduces ambiguity for names that
    exist across multiple brands. No literal product names are embedded here.
    """
    brand = str(product.get("brand") or "").strip()
    family = str(product.get("name") or "").strip()

    if brand and family:
        return f"{brand} {family}"

    return family or brand


def query_fallback(product: Dict[str, Any]) -> str:
    """
    Generic second query used only when the brand-qualified query produced no
    valid offer for that store.
    """
    return str(product.get("name") or "").strip()


def load_store_search(store: str):
    module = importlib.import_module(
        f"scrapers.{store}.scraper"
    )

    search_fn = getattr(module, "search", None)
    if not callable(search_fn):
        search_fn = getattr(module, "scrape", None)

    if not callable(search_fn):
        raise RuntimeError(
            f"{store}: scraper senza funzione search()/scrape()"
        )

    return search_fn


def run_store_for_product(
    store: str,
    product: Dict[str, Any],
) -> Tuple[str, str, List[Dict[str, Any]], Optional[str]]:
    """
    Refresh one canonical product in one store.

    The first attempt is brand-qualified. If it produces no valid offer, the
    generic family-only query is tried. The fallback is data-driven and is
    identical for every product/store combination.
    """
    try:
        # Import main lazily so indexer.py remains usable as a standalone
        # background process and does not initialize the API until needed.
        import main

        query = canonical_query(product)
        results = main.run_store(store, query)

        if not results:
            fallback = query_fallback(product)

            if fallback and main.norm(fallback) != main.norm(query):
                results = main.run_store(store, fallback)

        if not results:
            return store, product["product_id"], [], None

        return store, product["product_id"], results, None

    except Exception as exc:
        return (
            store,
            product["product_id"],
            [],
            f"{type(exc).__name__}: {exc}",
        )


def attach_canonical_identity(
    results: Iterable[Dict[str, Any]],
    product: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Attach the canonical catalog identity to offers already validated by the
    central scraper pipeline.

    Since this worker is refreshing one known catalog product at a time, the
    canonical product is the target identity. We still preserve the raw
    scraper fields untouched.
    """
    output: List[Dict[str, Any]] = []

    for item in results:
        if not isinstance(item, dict):
            continue

        enriched = dict(item)
        enriched["catalog_id"] = product["product_id"]
        enriched["product_identity"] = product["product_id"]
        enriched["canonical_brand"] = product["brand_name"]
        enriched["canonical_name"] = product["family_name"]

        if product.get("concentration"):
            enriched.setdefault(
                "canonical_concentration",
                product["concentration"],
            )

        output.append(enriched)

    return output


def refresh(
    catalog_path: Path | str = CATALOG_PATH,
    db_path: Path | str = DEFAULT_DB_PATH,
    stores: Sequence[str] = DEFAULT_STORES,
    workers: int = DEFAULT_WORKERS,
    offset: int = 0,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Refresh the local index.

    Work is bounded by `workers`; one slow store does not prevent other
    store/product jobs from completing and being written.
    """
    catalog = load_catalog(Path(catalog_path))

    if offset:
        catalog = catalog[offset:]

    if limit is not None:
        catalog = catalog[: max(0, int(limit))]

    selected_stores = [
        str(store).strip().lower()
        for store in stores
        if str(store).strip()
    ]

    # Validate store modules before starting network work.
    valid_stores: List[str] = []
    store_errors: Dict[str, str] = {}

    for store in selected_stores:
        try:
            load_store_search(store)
            valid_stores.append(store)
        except Exception as exc:
            store_errors[store] = (
                f"{type(exc).__name__}: {exc}"
            )

    if not valid_stores:
        raise RuntimeError("Nessun scraper valido disponibile.")

    total_jobs = len(catalog) * len(valid_stores)

    stats: Dict[str, Any] = {
        "catalog_products": len(catalog),
        "stores": valid_stores,
        "jobs": total_jobs,
        "completed_jobs": 0,
        "offers_written": 0,
        "errors": store_errors,
        "started_at": utc_now(),
        "elapsed_seconds": 0.0,
    }

    started = time.perf_counter()

    product_by_id = {
        item["product_id"]: item
        for item in catalog
    }

    with ProductIndex(db_path) as index:
        # Keep the canonical catalog available even if a store is temporarily
        # unreachable. This is important for autocomplete/search.
        # The catalog has already been loaded above. Reuse those exact
        # records instead of importing/loading it a second time.
        index.upsert_canonical_catalog(catalog)

        # Bounded concurrency across the full product/store matrix.
        # We deliberately do not create one executor per product.
        with ThreadPoolExecutor(
            max_workers=max(1, min(int(workers), len(valid_stores))),
            thread_name_prefix="scent_index",
        ) as executor:
            futures = {
                executor.submit(
                    run_store_for_product,
                    store,
                    product,
                ): (store, product)
                for product in catalog
                for store in valid_stores
            }

            for future in as_completed(futures):
                store, product = futures[future]

                try:
                    result_store, product_id, results, error = future.result()

                    if error:
                        stats["errors"][
                            f"{result_store}:{product_id}"
                        ] = error

                    if results:
                        target = product_by_id.get(product_id)

                        if target is not None:
                            enriched = attach_canonical_identity(
                                results,
                                target,
                            )
                            stats["offers_written"] += index.upsert_offers(
                                enriched
                            )

                except Exception as exc:
                    stats["errors"][
                        f"{store}:{product['product_id']}"
                    ] = (
                        f"{type(exc).__name__}: {exc}"
                    )
                    traceback.print_exc()

                stats["completed_jobs"] += 1

    stats["elapsed_seconds"] = round(
        time.perf_counter() - started,
        2,
    )
    stats["finished_at"] = utc_now()

    with ProductIndex(db_path) as index:
        stats["index"] = index.stats()

    return stats


def utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Aggiorna l'indice locale ScentHunter."
    )

    parser.add_argument(
        "--catalog",
        default=str(CATALOG_PATH),
        help="Percorso del product_catalog.json",
    )

    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB_PATH),
        help="Percorso del database SQLite locale",
    )

    parser.add_argument(
        "--stores",
        nargs="+",
        default=list(DEFAULT_STORES),
        help="Store da aggiornare",
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help="Numero massimo di aggiornamenti concorrenti",
    )

    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Salta i primi N prodotti del catalogo",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Aggiorna al massimo N prodotti",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    stats = refresh(
        catalog_path=args.catalog,
        db_path=args.db,
        stores=args.stores,
        workers=max(1, args.workers),
        offset=max(0, args.offset),
        limit=args.limit,
    )

    print(
        json.dumps(
            stats,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
