"""
ScentHunter — DIAGNOSTIC ONLY

Endpoint:
    /diagnose-liquid-brun?q=Liquid%20Brun

This module observes the existing scraper/discovery/validation pipeline.
It does not modify ProductMatcher, family_registry, scrapers, or frontend.
"""

from fastapi import APIRouter
import importlib
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

router = APIRouter()

STORES = [
    "bplatz",
    "deloox",
    "parfumcity",
    "parfumzentrum",
    "perfumemarket",
    "sabina",
    "orioudh",
    "easycosmetic",
]


def _main():
    return importlib.import_module("main")


def _run_one(store: str, query: str):
    main = _main()
    started = time.monotonic()

    row = {
        "store": store,
        "status": "ok",
        "raw": 0,
        "unique": 0,
        "valid": 0,
        "catalog": 0,
        "fallback": 0,
        "grouped": 0,
        "elapsed_sec": 0.0,
        "attempts": [],
        "products": [],
        "errors": [],
    }

    try:
        module = main.load_scraper(store)

        search_fn = getattr(module, "search", None)
        if not callable(search_fn):
            search_fn = getattr(module, "scrape", None)

        if not callable(search_fn):
            raise RuntimeError("scraper senza search()/scrape()")

        attempts = main.build_search_attempts(store, query)
        row["attempts"] = attempts

        candidates = []
        seen = set()

        for attempt in attempts:
            try:
                results = search_fn(attempt) or []
            except Exception as exc:
                row["errors"].append({
                    "stage": "discovery",
                    "attempt": attempt,
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

            if not isinstance(results, list):
                continue

            row["raw"] += len(results)

            for item in results:
                if not isinstance(item, dict):
                    continue

                product = dict(item)
                product.setdefault("store", store)

                key = main.product_identity_key(product)
                if key in seen:
                    continue

                seen.add(key)

                product = main.resolve_actual_price(product)

                image = main.product_image(product)
                if image:
                    product["image"] = image

                candidates.append(product)

        row["unique"] = len(candidates)

        accepted_products = []

        for product in candidates:
            try:
                if not main.matches(product, query):
                    continue

                row["valid"] += 1

                catalog_product = main._catalog_match(product, query)

                if catalog_product is not None:
                    row["catalog"] += 1
                    accepted = catalog_product
                else:
                    family = main._catalog_family_for_query(query)

                    if (
                        family is not None
                        and main._catalog_product_is_excluded(
                            product,
                            family,
                        )
                    ):
                        continue

                    row["fallback"] += 1
                    accepted = main._apply_generic_display_name(
                        product,
                        query,
                    )

                accepted_products.append(accepted)

                row["products"].append({
                    "name": (
                        accepted.get("name")
                        or accepted.get("display_name")
                        or ""
                    ),
                    "display_name": accepted.get(
                        "display_name",
                        "",
                    ),
                    "variant": accepted.get(
                        "variant",
                        "",
                    ),
                    "size_ml": main.product_size_ml(
                        accepted
                    ),
                    "price": accepted.get(
                        "price",
                        "",
                    ),
                    "url": accepted.get(
                        "url",
                        "",
                    ),
                    "catalog_variant": accepted.get(
                        "catalog_variant",
                        "",
                    ),
                    "family_id": accepted.get(
                        "family_id",
                        "",
                    ),
                })

            except Exception as exc:
                row["errors"].append({
                    "stage": "validation",
                    "error": f"{type(exc).__name__}: {exc}",
                })

        propagated = main._propagate_catalog_identity(
            accepted_products
        )

        grouped = main._group_catalog_results(
            propagated
        )

        row["grouped"] = len(grouped)

    except Exception as exc:
        row["status"] = "error"
        row["errors"].append({
            "stage": "store",
            "error": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        })

    row["elapsed_sec"] = round(
        time.monotonic() - started,
        3,
    )

    return row


@router.get("/diagnose-liquid-brun")
def diagnose_liquid_brun(
    q: str = "Liquid Brun",
):
    query = str(q or "").strip() or "Liquid Brun"
    started = time.monotonic()

    with ThreadPoolExecutor(
        max_workers=len(STORES),
        thread_name_prefix="diag",
    ) as pool:

        futures = {
            pool.submit(
                _run_one,
                store,
                query,
            ): store
            for store in STORES
        }

        rows = []

        for future in as_completed(futures):
            store = futures[future]

            try:
                rows.append(
                    future.result()
                )
            except Exception as exc:
                rows.append({
                    "store": store,
                    "status": "error",
                    "error": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                })

    rows.sort(
        key=lambda item: (
            STORES.index(item["store"])
            if item.get("store") in STORES
            else 999
        )
    )

    return {
        "diagnostic": True,
        "query": query,
        "elapsed_sec": round(
            time.monotonic() - started,
            3,
        ),
        "stores": rows,
        "interpretation": {
            "raw_0": (
                "discovery/scraper did not return candidates"
            ),
            "unique_positive_valid_0": (
                "candidates discovered but rejected "
                "by central validation"
            ),
            "valid_positive_grouped_lower": (
                "loss in catalog/grouping"
            ),
            "status_error": (
                "runtime/import/scraper execution problem"
            ),
        },
    }
