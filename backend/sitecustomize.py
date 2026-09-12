"""
ScentHunter streaming bootstrap with timing diagnostics.

This is based on the current working streaming bootstrap. It keeps the
existing scraper logic and adds diagnostic fields to PerfumeMarket and
Deloox results so /search-status exposes discovery and first-result timing.
The frontend can ignore fields beginning with "_diagnostic_".
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


def _diag_emit(s, emit, row, started):
    if not isinstance(row, dict):
        return
    diag = getattr(s, "_stream_diag", None)
    if not isinstance(diag, dict):
        diag = {"started": started}
        s._stream_diag = diag
    if "first_result_elapsed" not in diag:
        diag["first_result_elapsed"] = round(time.monotonic() - started, 3)
    if "discovery_elapsed" in diag:
        row["_diagnostic_discovery_elapsed"] = diag["discovery_elapsed"]
    row["_diagnostic_first_result_elapsed"] = diag["first_result_elapsed"]
    emit(row)


def _install_bplatz():
    try:
        from scrapers.bplatz import scraper as s
    except Exception:
        return
    if hasattr(s, "search_stream"):
        return

    def search_stream(query, emit):
        query = str(query or "").strip()
        if not query:
            return None
        import requests
        session = requests.Session()
        try:
            candidates = s.predictive_products(session, query)
        finally:
            session.close()
        if not candidates:
            return None
        with ThreadPoolExecutor(max_workers=min(8, len(candidates))) as pool:
            futures = [pool.submit(s.product_worker, c, query) for c in candidates]
            for future in as_completed(futures):
                try:
                    rows = future.result() or []
                except Exception:
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        emit(row)
        return None
    s.search_stream = search_stream


def _install_parfumcity():
    try:
        from scrapers.parfumcity import scraper as s
    except Exception:
        return
    if hasattr(s, "search_stream"):
        return

    def search_stream(query, emit):
        query = s.clean(query)
        if not query:
            return None
        s.CURRENT_QUERY = query
        session = s.requests.Session()
        try:
            urls = s._discover(session, query)
        finally:
            session.close()
        if not urls:
            return None

        def enrich(url):
            local = s.requests.Session()
            try:
                data = s._product_json(local, url)
                if not data:
                    return []
                rows = []
                for variant in data.get("variants") or []:
                    if not isinstance(variant, dict):
                        continue
                    item = s._item(data, variant, url)
                    if item:
                        rows.append(item)
                return rows
            finally:
                local.close()

        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
            futures = [pool.submit(enrich, url) for url in urls]
            for future in as_completed(futures):
                try:
                    rows = future.result() or []
                except Exception:
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        emit(row)
        return None
    s.search_stream = search_stream


def _install_perfumemarket():
    try:
        from scrapers.perfumemarket import scraper as s
    except Exception:
        return
    if hasattr(s, "search_stream"):
        return

    def search_stream(query, emit):
        query = s.clean(query)
        if not query:
            return None

        started = time.monotonic()
        s._stream_diag = {"started": started}

        session = s.requests.Session()
        try:
            candidates = s.discover(session, query)
        finally:
            session.close()

        s._stream_diag["discovery_elapsed"] = round(
            time.monotonic() - started, 3
        )

        if not candidates:
            return None

        with ThreadPoolExecutor(
            max_workers=min(max(8, s.PRODUCT_WORKERS), len(candidates))
        ) as pool:
            futures = [
                pool.submit(s.enrich_candidate, candidate, query)
                for candidate in candidates
            ]
            for future in as_completed(futures):
                try:
                    rows = future.result() or []
                except Exception:
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        _diag_emit(s, emit, row, started)

        return None

    s.search_stream = search_stream


def _install_deloox():
    try:
        from scrapers.deloox import scraper as s
    except Exception:
        return
    if hasattr(s, "search_stream"):
        return

    def search_stream(query, emit):
        query = s.clean(query)
        if not query:
            return None

        started = time.monotonic()
        s._stream_diag = {"started": started}

        session = s.requests.Session()
        try:
            urls = s.discover(session, query)
        finally:
            session.close()

        s._stream_diag["discovery_elapsed"] = round(
            time.monotonic() - started, 3
        )

        if not urls:
            return None

        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
            futures = [
                pool.submit(s.parse_product, url, query)
                for url in urls
            ]
            for future in as_completed(futures):
                try:
                    rows = future.result() or []
                except Exception:
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        _diag_emit(s, emit, row, started)

        return None

    s.search_stream = search_stream


def _install_orioudh():
    try:
        from scrapers.orioudh import scraper as s
    except Exception:
        return
    if hasattr(s, "search_stream"):
        return

    def search_stream(query, emit):
        query = s.clean(query)
        if not query:
            return None

        s.CURRENT_QUERY = query

        session = s.requests.Session()
        try:
            urls = s._discover(session, query)
        finally:
            session.close()

        if not urls:
            return None

        def enrich(url):
            local = s.requests.Session()
            try:
                data = s._product_json(local, url)
                if not data:
                    return []
                rows = []
                for variant in data.get("variants") or []:
                    if not isinstance(variant, dict):
                        continue
                    item = s._item(data, variant, url)
                    if item:
                        rows.append(item)
                return rows
            finally:
                local.close()

        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
            futures = [pool.submit(enrich, url) for url in urls]
            for future in as_completed(futures):
                try:
                    rows = future.result() or []
                except Exception:
                    continue
                for row in rows:
                    if isinstance(row, dict):
                        emit(row)

        return None

    s.search_stream = search_stream


for _installer in (
    _install_bplatz,
    _install_parfumcity,
    _install_perfumemarket,
    _install_deloox,
    _install_orioudh,
):
    try:
        _installer()
    except Exception:
        pass
