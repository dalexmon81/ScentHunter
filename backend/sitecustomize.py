"""
ScentHunter streaming bootstrap.

Compatibility rules:
- The main worker always calls search_stream(query, on_result).
- Existing scrapers are not rewritten.
- Each adapter uses only functions that actually exist in the corresponding
  scraper module.

This file is a COMPLETE replacement for backend/sitecustomize.py.
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
        diag["first_result_elapsed"] = round(
            time.monotonic() - started,
            3,
        )

    if "discovery_elapsed" in diag:
        row["_diagnostic_discovery_elapsed"] = (
            diag["discovery_elapsed"]
        )

    row["_diagnostic_first_result_elapsed"] = (
        diag["first_result_elapsed"]
    )

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
            candidates = s.predictive_products(
                session,
                query,
            )
        finally:
            session.close()

        if not candidates:
            return None

        with ThreadPoolExecutor(
            max_workers=min(
                8,
                len(candidates),
            )
        ) as pool:
            futures = [
                pool.submit(
                    s.product_worker,
                    candidate,
                    query,
                )
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
            urls = s._discover(
                session,
                query,
            )
        finally:
            session.close()

        if not urls:
            return None

        def enrich(url):
            local = s.requests.Session()

            try:
                data = s._product_json(
                    local,
                    url,
                )

                if not data:
                    return []

                rows = []

                for variant in (
                    data.get("variants") or []
                ):
                    if not isinstance(
                        variant,
                        dict,
                    ):
                        continue

                    item = s._item(
                        data,
                        variant,
                        url,
                    )

                    if item:
                        rows.append(item)

                return rows

            finally:
                local.close()

        with ThreadPoolExecutor(
            max_workers=min(
                8,
                len(urls),
            )
        ) as pool:
            futures = [
                pool.submit(
                    enrich,
                    url,
                )
                for url in urls
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
        s._stream_diag = {
            "started": started,
        }

        session = s.requests.Session()

        try:
            candidates = s.discover(
                session,
                query,
            )
        finally:
            session.close()

        s._stream_diag["discovery_elapsed"] = round(
            time.monotonic() - started,
            3,
        )

        if not candidates:
            return None

        with ThreadPoolExecutor(
            max_workers=min(
                max(
                    8,
                    s.PRODUCT_WORKERS,
                ),
                len(candidates),
            )
        ) as pool:
            futures = [
                pool.submit(
                    s.enrich_candidate,
                    candidate,
                    query,
                )
                for candidate in candidates
            ]

            for future in as_completed(futures):
                try:
                    rows = future.result() or []
                except Exception:
                    continue

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

        s._stream_diag = {
            "started": started,
        }

        session = s.requests.Session()

        try:
            candidates = s.discover(
                session,
                query,
            )
        finally:
            session.close()

        s._stream_diag["discovery_elapsed"] = round(
            time.monotonic() - started,
            3,
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

                # Current discover() returns
                # (score, context_or_title, image).
                # Older versions returned (score, context).
                if (
                    isinstance(
                        info,
                        (tuple, list),
                    )
                    and len(info) >= 3
                ):
                    score = info[0]
                    context = info[1]
                    image = info[2]
                elif (
                    isinstance(
                        info,
                        (tuple, list),
                    )
                    and len(info) == 2
                ):
                    score = info[0]
                    context = info[1]
                    image = ""
                else:
                    continue

            except (
                TypeError,
                ValueError,
            ):
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
                    row = s._row_from_card(
                        url,
                        context,
                        query,
                    )
                except Exception:
                    row = None

            elif len(info) >= 3 and image:
                try:
                    row = s._row_from_card(
                        url,
                        context,
                        query,
                        image,
                    )
                except Exception:
                    row = None

            if isinstance(row, dict):
                _diag_emit(
                    s,
                    emit,
                    row,
                    started,
                )
            else:
                missing.append(
                    (url, info)
                )

        # Only product pages whose discovery card was incomplete are fetched.
        if missing:
            with ThreadPoolExecutor(
                max_workers=min(
                    8,
                    len(missing),
                )
            ) as pool:
                futures = [
                    pool.submit(
                        s.parse_product,
                        url,
                        query,
                    )
                    for url, _ in missing
                ]

                for future in as_completed(futures):
                    try:
                        rows = future.result() or []
                    except Exception:
                        continue

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
            urls = s._discover(
                session,
                query,
            )
        finally:
            session.close()

        if not urls:
            return None

        def enrich(url):
            local = s.requests.Session()

            try:
                data = s._product_json(
                    local,
                    url,
                )

                if not data:
                    return []

                rows = []

                for variant in (
                    data.get("variants") or []
                ):
                    if not isinstance(
                        variant,
                        dict,
                    ):
                        continue

                    item = s._item(
                        data,
                        variant,
                        url,
                    )

                    if item:
                        rows.append(item)

                return rows

            finally:
                local.close()

        with ThreadPoolExecutor(
            max_workers=min(
                8,
                len(urls),
            )
        ) as pool:
            futures = [
                pool.submit(
                    enrich,
                    url,
                )
                for url in urls
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


def _install_sabina():
    """
    Complete Sabina streaming adapter.

    Born in Roma hardening is integrated here so this file is self-contained:
    - lower Sabina product-page concurrency;
    - slightly longer connection/read timeout;
    - Born in Roma first-party category discovery reserve;
    - conservative one-page fallback when the normal extractor returns [].

    No product identity, matcher or catalog rules are changed here.
    """
    try:
        from scrapers.sabina import scraper as s
    except Exception:
        return

    if hasattr(s, "search_stream"):
        return

    # The diagnostic showed 19 discovered URLs but only 5 extracted.
    # Eight simultaneous Sabina requests are unnecessarily aggressive for
    # this storefront. Four keeps the stream bounded while reducing transient
    # empty responses/timeouts.
    s.PRODUCT_WORKERS = 4
    s.CONNECT_TIMEOUT = 3.5
    s.READ_TIMEOUT = 6.5
    s.TIMEOUT = (
        s.CONNECT_TIMEOUT,
        s.READ_TIMEOUT,
    )

    original_extract = s._extract_product_page
    original_discover = s._discover_from_first_party

    def fallback_extract(url, query):
        """
        Conservative page extraction fallback.

        It runs only when the real extractor returned no rows.
        It uses the same existing Sabina parsing helpers and never fabricates
        a multi-variant price/size matrix.
        """
        session = s.requests.Session()
        session.headers.update(s.HEADERS)

        try:
            try:
                response = session.get(
                    url,
                    timeout=s.TIMEOUT,
                    allow_redirects=True,
                )
            except s.requests.RequestException:
                return []

            try:
                if response.status_code != 200:
                    return []

                html_text = response.text
                final_url = (
                    s._clean_product_url(
                        response.url
                    )
                    or url
                )
            finally:
                response.close()

            soup = s.BeautifulSoup(
                html_text or "",
                "html.parser",
            )

            product = s._jsonld_product(soup)
            title = s._extract_product_name(
                product,
                soup,
            )

            if not title:
                return []

            if not s._query_matches(
                title,
                final_url,
                query,
            ):
                return []

            if s._contains_non_product_term(
                title,
                final_url,
            ):
                return []

            brand = s._extract_brand(
                product,
                soup,
            )

            price, currency, price_source = (
                s._extract_price_and_currency(
                    product,
                    soup,
                    final_url,
                )
            )

            availability, availability_source = (
                s._availability_from_product(
                    product,
                    soup,
                )
            )

            size, size_source = (
                s._extract_size_from_product(
                    product,
                    title,
                )
            )

            concentration = s._concentration(
                title
            )

            image = s._extract_image(
                product,
                soup,
            )

            gtin = s._extract_gtin(
                product
            )

            mpn = s._jsonld_value(
                product,
                "mpn",
            )

            sku = s._jsonld_value(
                product,
                "sku",
            )

            product_id = (
                s._jsonld_value(
                    product,
                    "productID",
                    "productId",
                )
                or sku
            )

            if (
                price is None
                and availability == "unknown"
            ):
                return []

            result = s._build_result(
                title=title,
                brand=brand,
                price=price,
                currency=currency,
                availability=availability,
                availability_source=availability_source,
                size_ml=size,
                size_source=size_source,
                concentration=concentration,
                image=image,
                gtin=gtin,
                mpn=mpn,
                sku=sku,
                product_id=product_id,
                url=final_url,
                price_source=price_source,
            )

            return (
                [result]
                if isinstance(result, dict)
                else []
            )

        finally:
            session.close()

    def patched_extract(url, query):
        rows = original_extract(
            url,
            query,
        )

        if rows:
            return rows

        # One controlled retry with the same real page. This is intentionally
        # not a generic infinite retry loop.
        try:
            return fallback_extract(
                url,
                query,
            )
        except Exception:
            return []

    s._extract_product_page = patched_extract

    def patched_discover(session, query):
        urls = list(
            original_discover(
                session,
                query,
            )
            or []
        )

        query_norm = " ".join(
            str(query or "").casefold().split()
        )

        if (
            "born" not in query_norm
            or "roma" not in query_norm
        ):
            return urls

        seen = set(urls)

        # Sabina's first-party Valentino "Ver todos" page is a second
        # discovery source for Born in Roma. It is deliberately used only
        # for this family so generic searches remain unchanged.
        category_url = (
            s.BASE
            + "/es/654-ver-todos"
        )

        try:
            response = session.get(
                category_url,
                headers=s.HEADERS,
                timeout=s.TIMEOUT,
                allow_redirects=True,
            )
        except s.requests.RequestException:
            return urls[:s.MAX_CANDIDATES]

        try:
            if response.status_code != 200:
                return urls[:s.MAX_CANDIDATES]

            extra = (
                s._extract_product_links_from_html(
                    response.text or "",
                    query,
                )
            )
        finally:
            response.close()

        for link in extra:
            if link in seen:
                continue

            seen.add(link)
            urls.append(link)

            if len(urls) >= s.MAX_CANDIDATES:
                break

        return urls[:s.MAX_CANDIDATES]

    s._discover_from_first_party = patched_discover

    def search_stream(query, emit):
        query = s._clean(query)

        if not query:
            return None

        started = time.monotonic()

        s._stream_diag = {
            "started": started,
        }

        import requests

        session = requests.Session()

        try:
            urls = s._discover_from_first_party(
                session,
                query,
            )
        finally:
            session.close()

        s._stream_diag["discovery_elapsed"] = round(
            time.monotonic() - started,
            3,
        )

        if not urls:
            return None

        urls = list(
            dict.fromkeys(urls)
        )

        with ThreadPoolExecutor(
            max_workers=min(
                getattr(
                    s,
                    "PRODUCT_WORKERS",
                    4,
                ),
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

                if isinstance(
                    rows,
                    dict,
                ):
                    rows = [rows]

                for row in rows:
                    if isinstance(
                        row,
                        dict,
                    ):
                        _diag_emit(
                            s,
                            emit,
                            row,
                            started,
                        )

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

    original = getattr(
        s,
        "search_stream",
        None,
    )

    if not callable(original):
        return

    if getattr(
        s,
        "_scenthunter_stream_compat",
        False,
    ):
        return

    def search_stream(query, emit):
        for row in original(query):
            if isinstance(
                row,
                dict,
            ):
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
