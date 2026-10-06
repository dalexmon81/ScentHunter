"""ScentHunter - isolated family coverage worker.

This process is deliberately outside FastAPI/search. It reads the generic
family registry, asks the existing Deloox retailer scraper for family-level
queries, and persists only the discovered Deloox product URLs through the
catalog engine's existing persistence handoff.

It never calls /search, search_local(), ProductMatcher, or the frontend.
"""

from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path

import requests

from catalog_engine import _deloox_persist_products, _deloox_queue_allowed
from scrapers.deloox.scraper import _discover


BASE_DIR = Path(__file__).resolve().parent
REGISTRY_PATH = BASE_DIR / "family_registry.json"

# The first cycle starts shortly after the API process starts. Subsequent
# coverage cycles are deliberately infrequent: this is maintenance coverage,
# not request-time search.
START_DELAY_SECONDS = float(
    os.environ.get("SCENTHUNTER_FAMILY_COVERAGE_START_DELAY", "15")
)
INTERVAL_SECONDS = float(
    os.environ.get("SCENTHUNTER_FAMILY_COVERAGE_INTERVAL", "21600")
)

STOP = False


def _stop(signum, _frame):
    global STOP
    STOP = True
    print(f"FAMILY COVERAGE STOP signal={signum}", flush=True)


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def _load_queries():
    """Build generic retailer-family queries from family_registry.json."""
    with REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    families = payload.get("families") if isinstance(payload, dict) else None
    if not isinstance(families, list):
        return []

    queries = []
    seen = set()

    for family in families:
        if not isinstance(family, dict):
            continue

        family_id = str(family.get("family_id") or "").strip()
        aliases = family.get("query_aliases") or []

        if not isinstance(aliases, list):
            aliases = []

        family_queries = []
        for value in aliases:
            query = str(value or "").strip()
            if query:
                family_queries.append(query)

        # Generic registry-data fallback for a family without query aliases.
        # This does not encode any product-specific exception.
        if not family_queries:
            products = family.get("products") or []
            if isinstance(products, list):
                for product in products:
                    if not isinstance(product, dict):
                        continue
                    query = str(product.get("canonical_name") or "").strip()
                    if query:
                        family_queries.append(query)
                        break

        for query in family_queries:
            key = query.casefold()
            if key in seen:
                continue
            seen.add(key)
            queries.append((family_id, query))

    return queries


def _discover_family(session, family_id, query):
    started = time.monotonic()

    try:
        urls = _discover(session, query) or []
    except Exception as exc:
        return {
            "family_id": family_id,
            "query": query,
            "returned": 0,
            "candidate_urls": 0,
            "persisted": 0,
            "elapsed": round(time.monotonic() - started, 3),
            "error": f"{type(exc).__name__}:{exc}",
        }

    product_urls = {}

    for raw in urls:
        if not raw:
            continue

        url = str(raw).split("#", 1)[0]

        try:
            allowed = bool(_deloox_queue_allowed(url))
        except Exception:
            allowed = False

        if allowed:
            product_urls[url] = ""

    persisted = 0

    if product_urls:
        try:
            persisted = int(_deloox_persist_products(product_urls) or 0)
        except Exception as exc:
            return {
                "family_id": family_id,
                "query": query,
                "returned": len(urls),
                "candidate_urls": len(product_urls),
                "persisted": 0,
                "elapsed": round(time.monotonic() - started, 3),
                "error": f"persist:{type(exc).__name__}:{exc}",
            }

    return {
        "family_id": family_id,
        "query": query,
        "returned": len(urls),
        "candidate_urls": len(product_urls),
        "persisted": persisted,
        "elapsed": round(time.monotonic() - started, 3),
        "error": None,
    }


def run_once():
    """Run one complete generic family-coverage pass for Deloox."""
    queries = _load_queries()

    if not queries:
        print("FAMILY COVERAGE: no registry queries found", flush=True)
        return

    session = requests.Session()
    total_returned = 0
    total_persisted = 0

    print(
        f"FAMILY COVERAGE START queries={len(queries)} store=deloox",
        flush=True,
    )

    try:
        for family_id, query in queries:
            if STOP:
                break

            result = _discover_family(session, family_id, query)

            total_returned += int(result.get("returned") or 0)
            total_persisted += int(result.get("persisted") or 0)

            print(
                "FAMILY COVERAGE "
                f"family={family_id or '-'} "
                f"query={query!r} "
                f"returned={result.get('returned', 0)} "
                f"candidates={result.get('candidate_urls', 0)} "
                f"persisted={result.get('persisted', 0)} "
                f"elapsed={result.get('elapsed', 0)} "
                f"error={result.get('error') or '-'}",
                flush=True,
            )
    finally:
        session.close()

    print(
        f"FAMILY COVERAGE END returned={total_returned} "
        f"persisted={total_persisted}",
        flush=True,
    )


def main():
    print(
        f"FAMILY COVERAGE WORKER START pid={os.getpid()} "
        f"interval={INTERVAL_SECONDS}s",
        flush=True,
    )

    if START_DELAY_SECONDS > 0:
        deadline = time.monotonic() + START_DELAY_SECONDS
        while not STOP and time.monotonic() < deadline:
            time.sleep(min(1.0, deadline - time.monotonic()))

    while not STOP:
        try:
            run_once()
        except Exception as exc:
            print(
                "FAMILY COVERAGE CYCLE ERROR: "
                f"{type(exc).__name__}:{exc}",
                flush=True,
            )

        if STOP:
            break

        deadline = time.monotonic() + max(60.0, INTERVAL_SECONDS)

        while not STOP and time.monotonic() < deadline:
            time.sleep(min(5.0, deadline - time.monotonic()))

    print("FAMILY COVERAGE WORKER STOP", flush=True)


if __name__ == "__main__":
    main()
