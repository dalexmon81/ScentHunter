"""
ScentHunter streaming bootstrap.

This file is intentionally additive: existing scraper parsing is reused.
It injects search_stream(query, emit) into the scrapers that already expose
parallel discovery/product functions. No frontend changes and no scraper
parsing rewrites are required.

Python loads sitecustomize automatically for the worker subprocess because
backend is the worker cwd/PYTHONPATH.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed


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

        session = s.requests.Session()
        try:
            candidates = s.discover(session, query)
        finally:
            session.close()

        if not candidates:
            return None

        with ThreadPoolExecutor(max_workers=min(max(8, s.PRODUCT_WORKERS), len(candidates))) as pool:
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
                        emit(row)

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

        session = s.requests.Session()
        try:
            urls = s.discover(session, query)
        finally:
            session.close()

        if not urls:
            return None

        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
            futures = [pool.submit(s.parse_product, url, query) for url in urls]
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


# Install only after the interpreter is ready. Import failures are isolated
# so one broken optional scraper cannot prevent the API from starting.
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
