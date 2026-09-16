"""
ScentHunter streaming bootstrap.

Compatibility rules:
- The main worker always calls search_stream(query, on_result).
- Existing scrapers are not rewritten.
- Each adapter uses only functions that actually exist in the corresponding
  scraper module.
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
            futures = [
                pool.submit(s.product_worker, candidate, query)
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
    """
    Adapter for the CURRENT Deloox scraper.

    Important: the current Deloox module exposes:
      - discover(session, query)
      - _row_from_card(url, context, query)
      - parse_product(url, query)

    It does NOT expose extract_candidates(). Older sitecustomize code called
    that removed function and swallowed the resulting AttributeError, making
    the streaming path silently empty.
    """
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
            candidates = s.discover(session, query)
        finally:
            session.close()

        s._stream_diag["discovery_elapsed"] = round(
            time.monotonic() - started, 3
        )

        if not candidates:
            return None

        # discover() returns:
        # [(url, (score, context)), ...]
        #
        # The card already contains the name/price in the normal case.
        # Publish those rows immediately instead of throwing them away.
        missing = []
        seen = set()

        for item in candidates:
            try:
                url, info = item
                # Current discover() returns (score, context_or_title, image).
                # Older versions returned (score, context). Accept both shapes.
                if isinstance(info, (tuple, list)) and len(info) >= 3:
                    score, context, image = info[0], info[1], info[2]
                elif isinstance(info, (tuple, list)) and len(info) == 2:
                    score, context = info
                    image = ""
                else:
                    continue
            except (TypeError, ValueError):
                continue

            if url in seen:
                continue
            seen.add(url)

            # With the current Deloox discover(), the second field is the
            # URL-derived title rather than the old card context. Therefore
            # the card price may be unavailable. Try the card only when the
            # shape provides a real context; otherwise enrich the product page.
            row = None
            if len(info) == 2:
                try:
                    row = s._row_from_card(url, context, query)
                except Exception:
                    row = None
            elif len(info) >= 3 and image:
                try:
                    row = s._row_from_card(url, context, query, image)
                except Exception:
                    row = None

            if isinstance(row, dict):
                _diag_emit(s, emit, row, started)
            else:
                missing.append((url, info))

        # Only product pages whose discovery card was incomplete are fetched.
        if missing:
            with ThreadPoolExecutor(
                max_workers=min(8, len(missing))
            ) as pool:
                futures = [
                    pool.submit(s.parse_product, url, query)
                    for url, _ in missing
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
            max_workers=min(getattr(s, "PRODUCT_WORKERS", 8), len(urls))
        ) as pool:
            futures = [
                pool.submit(s._extract_product_page, url, query)
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
                        _diag_emit(s, emit, row, started)

        return None

    s.search_stream = search_stream


def _install_notino():
    """
    Compatibility adapter only.

    The current Notino scraper already has its own search_stream(query)
    generator. The main worker calls every stream as search_stream(query,
    on_result). We wrap the existing generator without changing its search
    logic or Playwright implementation.
    """
    try:
        from scrapers.notino import scraper as s
    except Exception:
        return

    original = getattr(s, "search_stream", None)
    if not callable(original):
        return

    if getattr(s, "_scenthunter_stream_compat", False):
        return

    def search_stream(query, emit):
        for row in original(query):
            if isinstance(row, dict):
                emit(row)
        return None

    s.search_stream = search_stream
    s._scenthunter_stream_compat = True


for _installer in (
    _install_bplatz,
    _install_parfumcity,
    _install_perfumemarket,
    _install_deloox,
    _install_orioudh,
    _install_sabina,
    _install_notino,
):
    try:
        _installer()
    except Exception:
        # One optional scraper must never prevent the API from starting.
        pass
