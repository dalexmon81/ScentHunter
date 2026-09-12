"""
ScentHunter streaming bootstrap with timing diagnostics.

Targeted optimization: Deloox discovery + fast HTTP-first Sabina discovery.
All other store logic is unchanged.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse


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
            for future in futures:
                if not future.done():
                    future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)

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
            futures = [pool.submit(s.parse_product, url, query) for url in urls]
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


def _sabina_query_matches(text, query):
    norm = lambda x: re.sub(r"[^a-z0-9]+", " ", str(x or "").lower()).strip()
    wanted = [x for x in norm(query).split() if len(x) >= 3]
    hay = norm(text)
    return bool(wanted) and all(x in hay for x in wanted)


def _sabina_product_url(url):
    try:
        p = urlparse(url)
        if p.netloc.lower() not in {"sabina.com", "www.sabina.com"}:
            return None
        path = p.path.rstrip("/")
        if not re.match(r"^/(?:en|fr|it|es|de|pt)/", path, re.I):
            return None
        if re.search(r"/(?:content|search|buscar|ricerca|carrello|checkout|module|modules)(?:/|$)", path, re.I):
            return None
        return f"https://www.sabina.com{path}"
    except Exception:
        return None


def _sabina_parse_product(html, url, query):
    from bs4 import BeautifulSoup
    import json
    soup = BeautifulSoup(html, "html.parser")
    products = []
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            obj = stack.pop(0)
            if isinstance(obj, list):
                stack.extend(obj)
            elif isinstance(obj, dict):
                typ = obj.get("@type")
                types = typ if isinstance(typ, list) else [typ]
                if "Product" in types or "ProductGroup" in types:
                    products.append(obj)
                if isinstance(obj.get("@graph"), list):
                    stack.extend(obj["@graph"])
    product = products[0] if products else {}
    name = str(product.get("name") or "").strip()
    if not name:
        h1 = soup.find("h1")
        name = h1.get_text(" ", strip=True) if h1 else ""
    if not _sabina_query_matches(name or url, query):
        return []

    offers = product.get("offers")
    offers = [offers] if isinstance(offers, dict) else [x for x in offers or [] if isinstance(x, dict)] if isinstance(offers, list) else []
    offer = offers[0] if offers else {}
    price = offer.get("price")
    try:
        price_num = float(str(price).replace(",", ".")) if price is not None else None
    except Exception:
        price_num = None
    currency = str(offer.get("priceCurrency") or "EUR").upper()
    availability = str(offer.get("availability") or "").lower()
    available = None if not availability else ("outofstock" not in availability and "instock" in availability)
    if "outofstock" in availability or "soldout" in availability:
        available = False
    size_text = name + " " + soup.get_text(" ", strip=True)[:8000]
    m = re.search(r"(?<!\d)(\d+(?:[.,]\d+)?)\s*(ml|cl|dl|l)\b", size_text, re.I)
    size_ml = None
    if m:
        size_ml = float(m.group(1).replace(",", "."))
        unit = m.group(2).lower()
        if unit == "cl": size_ml *= 10
        elif unit == "dl": size_ml *= 100
        elif unit == "l": size_ml *= 1000
        if size_ml.is_integer(): size_ml = int(size_ml)
    brand = product.get("brand")
    if isinstance(brand, dict): brand = brand.get("name")
    if price_num is None:
        meta = soup.select_one('meta[property="product:price:amount"], meta[itemprop="price"], meta[name="price"]')
        if meta:
            try: price_num = float(str(meta.get("content") or meta.get_text()).replace(",", "."))
            except Exception: pass
    image = product.get("image")
    if isinstance(image, list): image = image[0] if image else None
    if isinstance(image, dict): image = image.get("url") or image.get("contentUrl")
    row = {
        "store": "Sabina",
        "name": name,
        "brand": str(brand or ""),
        "size_ml": size_ml,
        "price": f"{price_num:.2f} €" if price_num is not None else "",
        "price_num": price_num,
        "currency": currency,
        "available": available,
        "availability": "in_stock" if available is True else "out_of_stock" if available is False else "unknown",
        "url": url,
        "image": image,
        "concentration": "Eau de Parfum" if "eau de parfum" in name.lower() else "Extrait de Parfum" if "extrait" in name.lower() else "",
        "provenance": {"name": "sabina_fast_http_jsonld"},
    }
    return [row]


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
        from bs4 import BeautifulSoup
        encoded = quote_plus(query)
        endpoints = (
            f"{s.BASE}/en/search?controller=search&s={encoded}",
            f"{s.BASE}/en/search?s={encoded}",
            f"{s.BASE}/en/search?query={encoded}",
            f"{s.BASE}/en/?s={encoded}",
        )
        headers = dict(s.HEADERS)

        def probe(endpoint):
            session = requests.Session()
            session.headers.update(headers)
            try:
                r = session.get(endpoint, timeout=(2.5, 4.0), allow_redirects=True)
                if r.status_code >= 400:
                    return []
                soup = BeautifulSoup(r.text, "html.parser")
                found = []
                seen = set()
                for a in soup.select("a[href]"):
                    href = a.get("href")
                    url = _sabina_product_url(href)
                    if not url or url in seen:
                        continue
                    text = a.get_text(" ", strip=True)
                    if _sabina_query_matches(f"{text} {url}", query):
                        seen.add(url)
                        found.append(url)
                return found[:8]
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
                try: found = future.result() or []
                except Exception: found = []
                for url in found:
                    if url not in seen:
                        seen.add(url); urls.append(url)
                if urls:
                    break
        finally:
            for future in futures:
                if not future.done(): future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)

        s._stream_diag["discovery_elapsed"] = round(time.monotonic() - started, 3)
        if not urls:
            return None

        def fetch(url):
            session = requests.Session(); session.headers.update(headers)
            try:
                r = session.get(url, timeout=(2.5, 5.0), allow_redirects=True)
                if r.status_code >= 400: return []
                return _sabina_parse_product(r.text, url, query)
            except Exception:
                return []
            finally:
                session.close()

        with ThreadPoolExecutor(max_workers=min(6, len(urls))) as pool:
            futures = [pool.submit(fetch, url) for url in urls]
            for future in as_completed(futures):
                try: rows = future.result() or []
                except Exception: rows = []
                for row in rows:
                    _diag_emit(s, emit, row, started)
        return None

    s.search_stream = search_stream


for _installer in (
    _install_bplatz,
    _install_parfumcity,
    _install_perfumemarket,
    _install_deloox,
    _install_orioudh,
    _install_sabina,
):
    try:
        _installer()
    except Exception:
        pass
