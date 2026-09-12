"""
ScentHunter streaming bootstrap with timing diagnostics.

Targeted optimization: Deloox discovery only.
All other store logic is unchanged.
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

        # Deloox was spending ~43s in sequential discovery. The existing
        # scraper tries six first-party search URLs one after another.
        # Probe those same first-party URLs concurrently and move on as soon
        # as one returns relevant product URLs.
        encoded = s.quote_plus(query)
        endpoints = (
            f"{s.BASE}/en/search?query={encoded}",
            f"{s.BASE}/en/search?q={encoded}",
            f"{s.BASE}/en/search?search={encoded}",
            f"{s.BASE}/en/search?searchTerm={encoded}",
            f"https://www.deloox.nl/en/search?query={encoded}",
            f"https://www.deloox.es/en/search?query={encoded}",
        )

        def probe(endpoint):
            session = s.requests.Session()
            try:
                response = s.get(session, endpoint)
                if not response:
                    return []
                return s.extract_candidates(response.text, query)
            except Exception:
                return []
            finally:
                session.close()

        pool = ThreadPoolExecutor(max_workers=len(endpoints))
        futures = [pool.submit(probe, endpoint) for endpoint in endpoints]
        urls = []
        seen = set()

        try:
            for future in as_completed(futures):
                try:
                    found = future.result() or []
                except Exception:
                    found = []

                for url in found:
                    if url not in seen:
                        seen.add(url)
                        urls.append(url)

                if urls:
                    break
        finally:
            # Do not wait for slower/blocked discovery probes.
            for future in futures:
                if not future.done():
                    future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)

        # Preserve the original bounded first-party catalog fallback if all
        # search endpoints failed.
        if not urls:
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

def _install_sabina():
    try:
        from scrapers.sabina import scraper as s
    except Exception:
        return

    if hasattr(s, "search_stream"):
        return

    def search_stream(query, emit):
        query = s._clean(query)
        if not query:
            return None

        started = time.monotonic()
        s._stream_diag = {"started": started}

        import requests

        session = requests.Session()
        try:
            urls = s._discover_from_first_party(session, query)
        finally:
            session.close()

        s._stream_diag["discovery_elapsed"] = round(
            time.monotonic() - started, 3
        )

        if not urls:
            return None

        urls = list(dict.fromkeys(urls))

        with ThreadPoolExecutor(
            max_workers=min(
                getattr(s, "PRODUCT_WORKERS", 8),
                len(urls),
            )
        ) as pool:
            futures = [
                pool.submit(
                    s._extract_product_page,
                    url,
                    query,
                )
                for url in urls
            ]

            for future in as_completed(futures):
                try:
                    rows = future.result() or []
                except Exception:
                    continue

                if isinstance(rows, dict):
                    rows = [rows]

                for row in rows:
                    if isinstance(row, dict):
                        _diag_emit(
                            s,
                            emit,
                            row,
                            started,
                        )

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
