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
- attaches the canonical product_id only after validating the returned offer;
- never assigns a canonical product identity to an offer from another brand;
- keeps the local index usable even when one store fails;
- supports partial runs through --limit / --offset / --stores;
- writes only to the local SQLite index.

This is an offline/background updater. It is intentionally separate from main.py.
"""

from __future__ import annotations

import argparse
import importlib
import json
import time
import traceback

from concurrent.futures import (
    ThreadPoolExecutor,
    as_completed,
)

from pathlib import Path
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Optional,
    Sequence,
    Tuple,
)


# ============================================================
# CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

CATALOG_PATH = (
    BASE_DIR / "product_catalog.json"
)

DEFAULT_DB_PATH = (
    BASE_DIR / "scenthunter_index.db"
)

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


# ============================================================
# LAZY IMPORTS
# ============================================================

def _load_product_index():
    """
    Load ProductIndex and the canonical catalog loader lazily.

    Keeping these imports lazy allows this file to remain usable as a
    standalone background process.
    """
    from product_index import (
        ProductIndex,
        load_canonical_catalog,
    )

    return (
        ProductIndex,
        load_canonical_catalog,
    )


def _load_matcher():
    """
    Kept for compatibility with the existing ScentHunter architecture.

    The current indexer does not directly instantiate ProductMatcher because
    validation is performed by main.run_store().
    """
    from product_matcher import ProductMatcher

    return ProductMatcher


# ============================================================
# CATALOG
# ============================================================

def load_catalog(
    path: Path,
) -> List[Dict[str, Any]]:
    """
    Load and normalize the canonical product catalog.

    Only valid canonical products with a product_id and family_name are
    returned.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"Catalogo non trovato: {path}"
        )

    data = json.loads(
        path.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(data, dict):
        raise ValueError(
            "product_catalog.json deve contenere un oggetto JSON."
        )

    products = data.get(
        "products",
        [],
    )

    if not isinstance(products, list):
        raise ValueError(
            "Il campo 'products' del catalogo deve essere una lista."
        )

    output: List[
        Dict[str, Any]
    ] = []

    for item in products:
        if not isinstance(
            item,
            dict,
        ):
            continue

        product_id = str(
            item.get(
                "product_id"
            )
            or ""
        ).strip()

        brand = str(
            item.get(
                "brand_name"
            )
            or ""
        ).strip()

        family = str(
            item.get(
                "family_name"
            )
            or ""
        ).strip()

        if not product_id:
            continue

        if not family:
            continue

        aliases = item.get(
            "aliases"
        ) or []

        if not isinstance(
            aliases,
            list,
        ):
            aliases = []

        normalized_aliases = [
            str(value).strip()
            for value in aliases
            if str(value).strip()
        ]

        output.append(
            {
                "product_id": product_id,
                "catalog_id": product_id,
                "brand_id": str(
                    item.get(
                        "brand_id"
                    )
                    or ""
                ).strip(),
                "brand": brand,
                "brand_name": brand,
                "name": family,
                "family_name": family,
                "concentration": str(
                    item.get(
                        "concentration"
                    )
                    or ""
                ).strip(),
                "gender": item.get(
                    "gender"
                ),
                "aliases": normalized_aliases,
            }
        )

    return output


def canonical_query(
    product: Dict[str, Any],
) -> str:
    """
    Generic query for a canonical catalog product.

    Brand + family is preferred because it reduces ambiguity when the same
    fragrance name exists under different brands.
    """
    brand = str(
        product.get(
            "brand"
        )
        or ""
    ).strip()

    family = str(
        product.get(
            "name"
        )
        or ""
    ).strip()

    if brand and family:
        return f"{brand} {family}"

    return family or brand


# ============================================================
# STORE SCRAPERS
# ============================================================

def load_store_search(
    store: str,
):
    """
    Import the scraper for a store and return its search/scrape function.
    """
    module = importlib.import_module(
        f"scrapers.{store}.scraper"
    )

    search_fn = getattr(
        module,
        "search",
        None,
    )

    if not callable(
        search_fn
    ):
        search_fn = getattr(
            module,
            "scrape",
            None,
        )

    if not callable(
        search_fn
    ):
        raise RuntimeError(
            f"{store}: scraper senza funzione search()/scrape()"
        )

    return search_fn


def run_store_for_product(
    store: str,
    product: Dict[str, Any],
) -> Tuple[
    str,
    str,
    List[Dict[str, Any]],
    Optional[str],
]:
    """
    Refresh one canonical product in one store.

    IMPORTANT:
    The query is always brand-qualified.

    We intentionally do NOT use a family-only fallback here. A family-only
    fallback can return another brand and the caller would then risk assigning
    the wrong canonical product_id to that offer.
    """
    product_id = str(
        product.get(
            "product_id"
        )
        or ""
    ).strip()

    try:
        import main

        query = canonical_query(
            product
        )

        if not query:
            return (
                store,
                product_id,
                [],
                "query canonica vuota",
            )

        results = main.run_store(
            store,
            query,
        )

        if not results:
            return (
                store,
                product_id,
                [],
                None,
            )

        return (
            store,
            product_id,
            results,
            None,
        )

    except Exception as exc:
        return (
            store,
            product_id,
            [],
            f"{type(exc).__name__}: {exc}",
        )


# ============================================================
# CANONICAL VALIDATION
# ============================================================

def _norm_text(
    value: Any,
) -> str:
    """
    Small local normalization helper.

    The central main.norm() remains the primary normalization mechanism.
    This helper is used only for the final canonical identity check.
    """
    import re

    value = str(
        value or ""
    ).lower().strip()

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _product_search_text(
    product: Dict[str, Any],
) -> str:
    """
    Build searchable text from scraper output.
    """
    values = [
        product.get("name"),
        product.get("title"),
        product.get("product_name"),
        product.get("brand"),
        product.get("source_brand"),
        product.get("brand_name"),
        product.get("product_line"),
        product.get("variant"),
        product.get("url"),
    ]

    source = product.get(
        "source"
    )

    if isinstance(
        source,
        dict,
    ):
        values.extend(
            [
                source.get(
                    "source_name"
                ),
                source.get(
                    "source_brand"
                ),
                source.get(
                    "name"
                ),
                source.get(
                    "brand"
                ),
            ]
        )

    return _norm_text(
        " ".join(
            str(value or "")
            for value in values
        )
    )


def canonical_offer_matches(
    offer: Dict[str, Any],
    product: Dict[str, Any],
) -> bool:
    """
    Final safety check before attaching canonical product identity.

    main.run_store() already performs the central validation. This second
    check protects the persistent index from accidentally assigning an offer
    returned for another brand/product family.
    """
    search_text = _product_search_text(
        offer
    )

    if not search_text:
        return False

    brand = _norm_text(
        product.get(
            "brand_name"
        )
        or product.get(
            "brand"
        )
    )

    family = _norm_text(
        product.get(
            "family_name"
        )
        or product.get(
            "name"
        )
    )

    if brand:
        brand_tokens = [
            token
            for token in brand.split()
            if len(token) >= 2
        ]

        if brand_tokens and not all(
            token in search_text
            for token in brand_tokens
        ):
            return False

    if family:
        family_tokens = [
            token
            for token in family.split()
            if len(token) >= 2
        ]

        if family_tokens and not all(
            token in search_text
            for token in family_tokens
        ):
            return False

    return True


def attach_canonical_identity(
    results: Iterable[
        Dict[str, Any]
    ],
    product: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Attach canonical catalog identity to validated offers.

    Offers that fail the final brand/family safety check are discarded.
    """
    output: List[
        Dict[str, Any]
    ] = []

    for item in results:
        if not isinstance(
            item,
            dict,
        ):
            continue

        if not canonical_offer_matches(
            item,
            product,
        ):
            continue

        enriched = dict(
            item
        )

        product_id = str(
            product.get(
                "product_id"
            )
            or ""
        ).strip()

        brand_name = str(
            product.get(
                "brand_name"
            )
            or ""
        ).strip()

        family_name = str(
            product.get(
                "family_name"
            )
            or ""
        ).strip()

        enriched[
            "catalog_id"
        ] = product_id

        enriched[
            "product_identity"
        ] = product_id

        enriched[
            "canonical_brand"
        ] = brand_name

        enriched[
            "canonical_name"
        ] = family_name

        concentration = str(
            product.get(
                "concentration"
            )
            or ""
        ).strip()

        if concentration:
            enriched.setdefault(
                "canonical_concentration",
                concentration,
            )

        output.append(
            enriched
        )

    return output


# ============================================================
# REFRESH
# ============================================================

def refresh(
    catalog_path: Path | str = CATALOG_PATH,
    db_path: Path | str = DEFAULT_DB_PATH,
    stores: Sequence[
        str
    ] = DEFAULT_STORES,
    workers: int = DEFAULT_WORKERS,
    offset: int = 0,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Refresh the local ProductIndex.

    The canonical catalog is always written first.

    Store scraping then runs concurrently with a bounded worker pool.

    One store/product failure does not stop the complete refresh.
    """
    ProductIndex, load_canonical_catalog = (
        _load_product_index()
    )

    catalog_file = Path(
        catalog_path
    )

    database_file = Path(
        db_path
    )

    catalog = load_catalog(
        catalog_file
    )

    # --------------------------------------------------------
    # PARTIAL CATALOG
    # --------------------------------------------------------

    safe_offset = max(
        0,
        int(offset),
    )

    if safe_offset:
        catalog = catalog[
            safe_offset:
        ]

    if limit is not None:
        safe_limit = max(
            0,
            int(limit),
        )

        catalog = catalog[
            :safe_limit
        ]

    # --------------------------------------------------------
    # STORES
    # --------------------------------------------------------

    selected_stores = [
        str(store).strip().lower()
        for store in stores
        if str(store).strip()
    ]

    # Remove duplicates while preserving order.
    selected_stores = list(
        dict.fromkeys(
            selected_stores
        )
    )

    if not selected_stores:
        raise RuntimeError(
            "Nessun store selezionato."
        )

    valid_stores: List[str] = []

    store_errors: Dict[
        str,
        str,
    ] = {}

    for store in selected_stores:
        try:
            load_store_search(
                store
            )

            valid_stores.append(
                store
            )

        except Exception as exc:
            store_errors[
                store
            ] = (
                f"{type(exc).__name__}: {exc}"
            )

    if not valid_stores:
        raise RuntimeError(
            "Nessun scraper valido disponibile."
        )

    # --------------------------------------------------------
    # STATS
    # --------------------------------------------------------

    total_jobs = (
        len(catalog)
        * len(valid_stores)
    )

    stats: Dict[
        str,
        Any,
    ] = {
        "catalog_products": len(
            catalog
        ),
        "stores": valid_stores,
        "jobs": total_jobs,
        "completed_jobs": 0,
        "offers_found": 0,
        "offers_written": 0,
        "offers_rejected": 0,
        "errors": store_errors,
        "started_at": utc_now(),
        "elapsed_seconds": 0.0,
    }

    started = time.perf_counter()

    # --------------------------------------------------------
    # PRODUCT LOOKUP
    #
    # Avoid an O(n) next(...) for every completed future.
    # --------------------------------------------------------

    products_by_id: Dict[
        str,
        Dict[str, Any],
    ] = {
        str(
            product["product_id"]
        ): product
        for product in catalog
    }

    # --------------------------------------------------------
    # INDEX
    # --------------------------------------------------------

    with ProductIndex(
        database_file
    ) as index:

        # The complete canonical catalog is maintained independently from
        # live store availability.
        canonical_catalog = (
            load_canonical_catalog(
                catalog_file
            )
        )

        index.upsert_canonical_catalog(
            canonical_catalog
        )

        if total_jobs > 0:

            worker_count = max(
                1,
                min(
                    int(workers),
                    len(valid_stores),
                    total_jobs,
                ),
            )

            with ThreadPoolExecutor(
                max_workers=worker_count,
                thread_name_prefix="scent_index",
            ) as executor:

                futures = {
                    executor.submit(
                        run_store_for_product,
                        store,
                        product,
                    ): (
                        store,
                        product,
                    )
                    for product in catalog
                    for store in valid_stores
                }

                for future in as_completed(
                    futures
                ):
                    store, product = (
                        futures[future]
                    )

                    product_id = str(
                        product.get(
                            "product_id"
                        )
                        or ""
                    ).strip()

                    try:
                        (
                            result_store,
                            result_product_id,
                            results,
                            error,
                        ) = future.result()

                        if error:
                            stats[
                                "errors"
                            ][
                                f"{result_store}:{result_product_id}"
                            ] = error

                        if results:
                            stats[
                                "offers_found"
                            ] += len(
                                results
                            )

                            target = (
                                products_by_id.get(
                                    result_product_id
                                )
                            )

                            if target is None:
                                stats[
                                    "errors"
                                ][
                                    f"{result_store}:{result_product_id}"
                                ] = (
                                    "Product ID canonico non presente "
                                    "nel catalogo caricato"
                                )

                            else:
                                enriched = (
                                    attach_canonical_identity(
                                        results,
                                        target,
                                    )
                                )

                                rejected = (
                                    len(results)
                                    - len(enriched)
                                )

                                stats[
                                    "offers_rejected"
                                ] += max(
                                    0,
                                    rejected,
                                )

                                if enriched:
                                    written = (
                                        index.upsert_offers(
                                            enriched
                                        )
                                    )

                                    stats[
                                        "offers_written"
                                    ] += int(
                                        written
                                        or 0
                                    )

                    except Exception as exc:
                        stats[
                            "errors"
                        ][
                            f"{store}:{product_id}"
                        ] = (
                            f"{type(exc).__name__}: {exc}"
                        )

                        traceback.print_exc()

                    stats[
                        "completed_jobs"
                    ] += 1

    # --------------------------------------------------------
    # FINAL STATS
    # --------------------------------------------------------

    stats[
        "elapsed_seconds"
    ] = round(
        time.perf_counter()
        - started,
        2,
    )

    stats[
        "finished_at"
    ] = utc_now()

    with ProductIndex(
        database_file
    ) as index:
        stats[
            "index"
        ] = index.stats()

    return stats


# ============================================================
# TIME
# ============================================================

def utc_now() -> str:
    from datetime import (
        datetime,
        timezone,
    )

    return datetime.now(
        timezone.utc
    ).isoformat()


# ============================================================
# CLI
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggiorna l'indice locale ScentHunter."
        )
    )

    parser.add_argument(
        "--catalog",
        default=str(
            CATALOG_PATH
        ),
        help=(
            "Percorso del product_catalog.json"
        ),
    )

    parser.add_argument(
        "--db",
        default=str(
            DEFAULT_DB_PATH
        ),
        help=(
            "Percorso del database SQLite locale"
        ),
    )

    parser.add_argument(
        "--stores",
        nargs="+",
        default=list(
            DEFAULT_STORES
        ),
        help=(
            "Store da aggiornare"
        ),
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=DEFAULT_WORKERS,
        help=(
            "Numero massimo di aggiornamenti concorrenti"
        ),
    )

    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help=(
            "Salta i primi N prodotti del catalogo"
        ),
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help=(
            "Aggiorna al massimo N prodotti"
        ),
    )

    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main() -> int:
    args = parse_args()

    try:
        stats = refresh(
            catalog_path=args.catalog,
            db_path=args.db,
            stores=args.stores,
            workers=max(
                1,
                args.workers,
            ),
            offset=max(
                0,
                args.offset,
            ),
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

    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                    "traceback": traceback.format_exc(),
                },
                ensure_ascii=False,
                indent=2,
            )
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(
        main()
    )
