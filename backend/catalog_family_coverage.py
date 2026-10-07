"""ScentHunter - isolated family coverage worker.

Generic Deloox family coverage, deliberately outside FastAPI/search.

The worker:
- reads family_registry.json;
- tries the first generic alias for each family;
- only falls back to additional aliases when the previous alias returns no
  usable product URLs;
- persists each family's discovered URLs in one short catalog transaction;
- retries a locked SQLite write with backoff instead of hammering the DB.

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

START_DELAY_SECONDS = float(
    os.environ.get("SCENTHUNTER_FAMILY_COVERAGE_START_DELAY", "15")
)
INTERVAL_SECONDS = float(
    os.environ.get("SCENTHUNTER_FAMILY_COVERAGE_INTERVAL", "21600")
)

PERSIST_RETRIES = int(
    os.environ.get("SCENTHUNTER_FAMILY_COVERAGE_PERSIST_RETRIES", "5")
)
PERSIST_BACKOFF_SECONDS = (2.0, 5.0, 10.0, 20.0, 30.0)

STOP = False


# The family worker runs as a separate process from Uvicorn.  Thread-local
# checks in catalog_engine.py cannot see a foreground search from here.
# Linux exposes thread names through /proc, so use the same search-thread
# contract across the process boundary without changing FastAPI/main.py.
FOREGROUND_SEARCH_POLL_SECONDS = float(
    os.environ.get("SCENTHUNTER_FAMILY_COVERAGE_SEARCH_POLL", "0.5")
)


def _foreground_search_running():
    """Return True when any ScentHunter foreground search thread is active."""
    proc_root = Path("/proc")
    try:
        for process_dir in proc_root.iterdir():
            if not process_dir.name.isdigit():
                continue

            task_dir = process_dir / "task"
            try:
                for thread_dir in task_dir.iterdir():
                    try:
                        comm = (thread_dir / "comm").read_text(
                            encoding="utf-8",
                            errors="ignore",
                        ).strip()
                    except (OSError, UnicodeError):
                        continue

                    if comm.startswith("scenthunter-search-"):
                        return True
            except OSError:
                continue
    except OSError:
        return False

    return False


def _wait_for_foreground_idle():
    """Pause background coverage while a user search is running."""
    announced = False

    while not STOP and _foreground_search_running():
        if not announced:
            print(
                "FAMILY COVERAGE WAIT foreground_search=active",
                flush=True,
            )
            announced = True
        time.sleep(max(0.1, FOREGROUND_SEARCH_POLL_SECONDS))

    if announced and not STOP:
        print(
            "FAMILY COVERAGE RESUME foreground_search=idle",
            flush=True,
        )

    return not STOP


def _lower_process_priority():
    """Yield CPU scheduling priority to the foreground application."""
    try:
        os.nice(10)
        print("FAMILY COVERAGE PRIORITY nice=10", flush=True)
    except (AttributeError, OSError, PermissionError) as exc:
        print(
            "FAMILY COVERAGE PRIORITY unavailable "
            f"error={type(exc).__name__}:{exc}",
            flush=True,
        )


def _stop(signum, _frame):
    global STOP
    STOP = True
    print(f"FAMILY COVERAGE STOP signal={signum}", flush=True)


signal.signal(signal.SIGTERM, _stop)
signal.signal(signal.SIGINT, _stop)


def _load_queries():
    """Load generic family aliases from the registry.

    The first alias is preferred. Additional aliases are fallback queries for
    the same family and are used only when the earlier alias returns no
    admissible product URLs.
    """
    with REGISTRY_PATH.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    families = payload.get("families") if isinstance(payload, dict) else None
    if not isinstance(families, list):
        return []

    queries = []
    seen_families = set()

    for family in families:
        if not isinstance(family, dict):
            continue

        family_id = str(family.get("family_id") or "").strip()
        if not family_id or family_id in seen_families:
            continue
        seen_families.add(family_id)

        aliases = family.get("query_aliases") or []
        if not isinstance(aliases, list):
            aliases = []

        family_queries = []
        seen_aliases = set()

        for value in aliases:
            query = str(value or "").strip()
            key = query.casefold()
            if query and key not in seen_aliases:
                seen_aliases.add(key)
                family_queries.append(query)

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

        if family_queries:
            queries.append((family_id, family_queries))

    return queries


def _discover_urls(session, query):
    """Discover and filter admissible Deloox product URLs for one query."""
    urls = _discover(session, query) or []
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

    return urls, product_urls


def _persist_with_retry(product_urls):
    """Persist one family's URLs without repeatedly hammering a locked DB."""
    if not product_urls:
        return 0, None

    last_error = None
    retries = max(1, PERSIST_RETRIES)

    for attempt in range(retries):
        try:
            return int(_deloox_persist_products(product_urls) or 0), None
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()

            if "database is locked" not in message and "database is busy" not in message:
                return 0, f"{type(exc).__name__}:{exc}"

            if attempt + 1 >= retries:
                break

            delay = PERSIST_BACKOFF_SECONDS[
                min(attempt, len(PERSIST_BACKOFF_SECONDS) - 1)
            ]
            print(
                f"FAMILY COVERAGE DB BUSY retry={attempt + 1} "
                f"sleep={delay}s",
                flush=True,
            )
            time.sleep(delay)

    return 0, (
        f"persist:{type(last_error).__name__}:{last_error}"
        if last_error
        else "persist:database locked"
    )


def _discover_family(session, family_id, queries):
    started = time.monotonic()
    attempted = []
    selected_urls = {}
    returned_total = 0

    for query in queries:
        if STOP:
            break

        if not _wait_for_foreground_idle():
            break

        try:
            urls, product_urls = _discover_urls(session, query)
            returned_total += len(urls)
            attempted.append(
                {
                    "query": query,
                    "returned": len(urls),
                    "candidates": len(product_urls),
                }
            )

            # One successful generic alias is sufficient. Additional aliases
            # are fallbacks, not parallel discovery work.
            if product_urls:
                selected_urls = product_urls
                break

        except Exception as exc:
            attempted.append(
                {
                    "query": query,
                    "returned": 0,
                    "candidates": 0,
                    "error": f"{type(exc).__name__}:{exc}",
                }
            )

    if selected_urls and not _wait_for_foreground_idle():
        persisted, persist_error = 0, "stopped:foreground_search_active"
    else:
        persisted, persist_error = _persist_with_retry(selected_urls)

    return {
        "family_id": family_id,
        "queries": attempted,
        "returned": returned_total,
        "candidate_urls": len(selected_urls),
        "persisted": persisted,
        "elapsed": round(time.monotonic() - started, 3),
        "error": persist_error,
    }


def run_once():
    """Run one generic family-coverage pass for Deloox."""
    families = _load_queries()

    if not families:
        print("FAMILY COVERAGE: no registry queries found", flush=True)
        return

    session = requests.Session()
    total_returned = 0
    total_persisted = 0

    print(
        f"FAMILY COVERAGE START families={len(families)} store=deloox",
        flush=True,
    )

    try:
        for family_id, queries in families:
            if STOP:
                break

            result = _discover_family(session, family_id, queries)

            total_returned += int(result.get("returned") or 0)
            total_persisted += int(result.get("persisted") or 0)

            attempted = result.get("queries") or []
            attempted_text = "; ".join(
                f"{item.get('query')!r}:"
                f"{item.get('returned', 0)}/"
                f"{item.get('candidates', 0)}"
                for item in attempted
            )

            print(
                "FAMILY COVERAGE "
                f"family={family_id} "
                f"queries=[{attempted_text}] "
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

    _lower_process_priority()

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
