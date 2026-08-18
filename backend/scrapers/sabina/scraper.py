import re
import json
import sys
import time
import html as html_lib
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup

STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 6
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/it/",
}
PRICE_RE = re.compile(r"(?:€|\$|£)\s*(\d{1,4}(?:[.,]\d{2}))|(?<!\d)(\d{1,4}(?:[.,]\d{2}))\s*(?:€|\$|£)", re.I)
PRODUCT_URL_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/(?:it|fr|en|es|de|pt)/"
    r"(?!content|ricerca|ricerca_old|marchi|negozi|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module)", re.I
)

def _clean(value):
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()

def _price(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return f"{float(value):.2f}".replace(".", ",") + " €"
    text = _clean(value)
    m = PRICE_RE.search(text) or re.search(r"(?<!\d)(\d{1,4}(?:[.,]\d{2}))(?!\d)", text)
    value = next((g for g in m.groups() if g is not None), None) if m else None
    return (value.replace(".", ",") + " €") if value else None

def _looks_like_product_url(url):
    return bool(url and PRODUCT_URL_RE.match(url))

def _query_matches(name, url, query):
    """Match against both visible product name and product URL.

    Sabina may put searchable terms in the product URL even when the
    clickable product title is incomplete. Matching therefore uses both
    normalized product text and URL text.
    """
    q_words = [w for w in re.findall(r"[a-z0-9À-ÿ]+", _clean(query).lower()) if len(w) > 1]
    if not q_words:
        return False
    hay = f"{_clean(name).lower()} {str(url or '').lower().replace('-', ' ')}"
    return all(w in hay for w in q_words)

def _extract_size_from_html(text):
    if not text:
        return ""
    try:
        soup = BeautifulSoup(text, "html.parser")
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.get_text(strip=True))
            except Exception:
                continue
            stack = [data]
            while stack:
                obj = stack.pop()
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if str(k).lower() in {"size", "volume", "netcontent", "capacity", "contentvolume"}:
                            m = re.search(r"(?<!\d)(\d{2,4})\s*ml\b", str(v), re.I)
                            if m:
                                return m.group(1)
                        if isinstance(v, (dict, list)):
                            stack.append(v)
                elif isinstance(obj, list):
                    stack.extend(obj)
    except Exception:
        pass
    soup = BeautifulSoup(text, "html.parser")
    visible = _clean(soup.get_text(" ", strip=True))
    for pattern in (
        r"(?:dimensione|tamaño|taille|größe|groesse|size)\s*:?\s*(\d{2,4})\s*ml\b",
        r"(?:dimensione|tamaño|taille|größe|groesse|size)[^0-9]{0,120}(\d{2,4})\s*ml\b",
    ):
        m = re.search(pattern, visible, re.I)
        if m:
            return m.group(1)
    return ""

def _enrich_product_sizes(session, rows):
    out, cache = [], {}
    requests_used = 0
    for row in rows:
        item = dict(row)
        m = re.search(r"\b(\d{1,4})\s*ml\b", _clean(item.get("name")), re.I)
        if m:
            item["size_ml"] = m.group(1)
            out.append(item)
            continue
        url = str(item.get("url") or "").split("#")[0]
        size = cache.get(url, "")
        if url and not size and requests_used < 3:
            requests_used += 1
            try:
                r = _get(session, url)
                if r is not None:
                    size = _extract_size_from_html(r.text)
                    r.close()
            except Exception:
                size = ""
            cache[url] = size
        if size:
            item["size_ml"] = size
        out.append(item)
    return out

def _dedupe(rows, query):
    out, seen = [], set()
    for row in rows:
        name = _clean(row.get("name"))
        url = str(row.get("url") or "")
        price = _price(row.get("price"))
        if not name or not url or not price:
            continue
        if not _query_matches(name, url, query):
            continue
        key = (name.lower(), url.split("?")[0].split("#")[0])
        if key in seen:
            continue
        seen.add(key)
        item = {"store": STORE, "name": name, "price": price, "url": url.split("#")[0]}
        if row.get("size_ml"):
            item["size_ml"] = str(row["size_ml"])
        out.append(item)
    return out

def _walk_json(obj, query):
    rows = []
    def walk(x):
        if isinstance(x, dict):
            low = {str(k).lower(): v for k, v in x.items()}
            name = next((low[k] for k in ("name", "product_name", "productname", "title", "label") if k in low and isinstance(low[k], (str, int, float))), None)
            url = next((low[k] for k in ("url", "link", "product_url", "producturl", "href") if k in low and isinstance(low[k], str)), None)
            price = next((low[k] for k in ("price", "final_price", "finalprice", "sale_price", "saleprice", "price_amount", "priceamount") if k in low), None)
            if url:
                url = urljoin(BASE, url)
            if name and url and _looks_like_product_url(url) and _price(price):
                rows.append({"store": STORE, "name": str(name), "price": price, "url": url})
            for v in x.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(obj)
    return _dedupe(rows, query)

def _parse_html(text, query):
    soup = BeautifulSoup(text, "html.parser")
    rows = []
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            rows.extend(_walk_json(json.loads(script.get_text(strip=True)), query))
        except Exception:
            pass
    for a in soup.find_all("a", href=True):
        url = urljoin(BASE, a["href"])
        if not _looks_like_product_url(url):
            continue
        container = a
        for _ in range(7):
            parent = getattr(container, "parent", None)
            if not parent:
                break
            container = parent
            txt = _clean(container.get_text(" ", strip=True))
            if re.search(r"(?:€|\$|£)", txt) and len(txt) < 1800:
                break
        text_block = _clean(container.get_text(" ", strip=True))
        pm = PRICE_RE.search(text_block)
        if not pm:
            continue
        candidates = [a.get("title"), a.get("aria-label"), a.get_text(" ", strip=True)]
        for sel in ("h1", "h2", "h3", "h4", ".name", ".product-name", ".product-title", ".product-item-name"):
            for el in container.select(sel):
                candidates.append(el.get_text(" ", strip=True))
        cleaned = [_clean(x) for x in candidates if _clean(x)]
        if not cleaned:
            continue
        # Prefer the candidate that best represents the product title.
        # The score is entirely generic: query-token coverage first, then
        # semantic title attributes and reasonable title length.
        q_tokens = [
            token for token in re.findall(r"[a-z0-9à-ÿ]+", _clean(query).lower())
            if len(token) > 1
        ]

        def candidate_score(candidate):
            value = _clean(candidate)
            normalized = value.lower().replace("-", " ").replace("_", " ")
            token_hits = sum(1 for token in q_tokens if token in normalized)
            ui_penalty = 100 if normalized in {
                "vedi", "vedi tutto", "acquista", "immagine", "comprar",
                "buy", "see all", "view all", "add to cart", "carrello"
            } else 0
            length_penalty = max(0, len(value) - 180)
            return (token_hits, -ui_penalty, -length_penalty, -len(value))

        name = max(cleaned, key=candidate_score)
        if name.lower() in {"vedi", "vedi tutto", "acquista", "immagine"}:
            continue
        rows.append({"store": STORE, "name": name, "price": next((g for g in pm.groups() if g is not None), "") .replace(".", ",") + " €", "url": url})
    return _dedupe(rows, query)


def _query_tokens(query):
    text = _clean(query).lower()
    text = re.sub(r"(?<=\d)(?=[a-zà-ÿ])|(?<=[a-zà-ÿ])(?=\d)", " ", text)
    text = re.sub(r"[^a-z0-9à-ÿ]+", " ", text)
    return [token for token in text.split() if len(token) > 1]


def _query_match_score(name, url, query):
    wanted = _query_tokens(query)
    if not wanted:
        return 0
    hay = _clean(f"{name} {url}").lower().replace("-", " ").replace("_", " ")
    return sum(1 for token in wanted if token in hay)


def _extract_product_links_from_html(text, query):
    soup = BeautifulSoup(text, "html.parser")
    found = []
    seen = set()
    wanted_count = len(_query_tokens(query))

    for anchor in soup.find_all("a", href=True):
        url = urljoin(BASE, anchor.get("href") or "").split("#")[0]
        if not _looks_like_product_url(url):
            continue

        candidates = [
            anchor.get("title"),
            anchor.get("aria-label"),
            anchor.get_text(" ", strip=True),
            anchor.find("img").get("alt") if anchor.find("img") else None,
        ]

        node = anchor
        for _ in range(7):
            node = getattr(node, "parent", None)
            if node is None:
                break
            for selector in (
                '[itemprop="name"]',
                ".product-name",
                ".product-title",
                ".product-item-name",
                ".product-name-container",
                ".product-title-container",
                "h2", "h3", "h4",
            ):
                for element in node.select(selector):
                    candidates.append(element.get_text(" ", strip=True))
            block = _clean(node.get_text(" ", strip=True))
            if block:
                candidates.append(block)
            if re.search(r"(?:€|\$|£)", block) and len(block) < 2200:
                break

        score = max(
            (_query_match_score(candidate, url, query)
             for candidate in candidates if _clean(candidate)),
            default=_query_match_score("", url, query),
        )

        if score < wanted_count:
            continue

        path = url.split("?", 1)[0]
        if path not in seen:
            seen.add(path)
            found.append((score, path))

    found.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in found]


def _discover_from_search_page(session, query):
    urls = []
    seen = set()
    q = quote_plus(query)

    # Multiple generic forms of the site's own search endpoint. No product
    # or brand is embedded here; the runtime query is always supplied by the
    # caller.
    search_urls = [
        BASE + "/it/ricerca?controller=search&s=" + q,
        BASE + "/it/ricerca?s=" + q,
        BASE + "/it/ricerca?search_query=" + q,
        BASE + "/it/ricerca_old?s=" + q,
        BASE + "/it/ricerca_old?search_query=" + q,
    ]

    for url in search_urls:
        try:
            response = _get(session, url)
            if response is None:
                continue
            links = _extract_product_links_from_html(response.text, query)
            response.close()
        except requests.RequestException:
            continue

        for product_url in links:
            if product_url not in seen:
                seen.add(product_url)
                urls.append(product_url)

    return urls


def _xml_locs(text):
    try:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(text)
        return [
            element.text.strip()
            for element in root.iter()
            if element.tag.lower().endswith("loc")
            and element.text and element.text.strip()
        ]
    except Exception:
        return re.findall(r"<loc>\s*(.*?)\s*</loc>", text, flags=re.I | re.S)


def _discover_from_sitemap(session, query):
    # Sitemap discovery is only a generic fallback when the site's search
    # response does not expose usable product links.
    candidates = [
        BASE + "/sitemap.xml",
        BASE + "/1_index_sitemap.xml",
        BASE + "/it/sitemap.xml",
        BASE + "/en/sitemap.xml",
    ]

    try:
        response = _get(session, BASE + "/robots.txt")
        if response is not None:
            for line in response.text.splitlines():
                if line.lower().startswith("sitemap:"):
                    sitemap = line.split(":", 1)[1].strip()
                    if sitemap and sitemap not in candidates:
                        candidates.insert(0, sitemap)
            response.close()
    except requests.RequestException:
        pass

    product_urls = []
    child_maps = []
    seen_maps = set()

    for sitemap in candidates:
        if sitemap in seen_maps:
            continue
        seen_maps.add(sitemap)
        try:
            response = _get(session, sitemap)
            if response is None:
                continue
            locations = _xml_locs(response.text)
            response.close()
        except requests.RequestException:
            continue

        for loc in locations:
            if loc.lower().endswith(".xml") and "sitemap" in loc.lower():
                child_maps.append(loc)
            elif _looks_like_product_url(loc):
                product_urls.append(loc)

    # Follow a bounded number of child maps to avoid turning the fallback
    # into a full-site crawl.
    for sitemap in child_maps[:16]:
        if sitemap in seen_maps:
            continue
        seen_maps.add(sitemap)
        try:
            response = _get(session, sitemap)
            if response is None:
                continue
            locations = _xml_locs(response.text)
            response.close()
        except requests.RequestException:
            continue
        product_urls.extend(
            loc for loc in locations if _looks_like_product_url(loc)
        )

    wanted_count = len(_query_tokens(query))
    output = []
    seen = set()
    for url in product_urls:
        clean_url = url.split("#")[0].split("?")[0]
        if clean_url in seen:
            continue
        seen.add(clean_url)
        if _query_match_score("", clean_url, query) == wanted_count:
            output.append(clean_url)

    return output


def _discover_from_json_endpoints(session, query):
    urls = []
    seen = set()
    endpoints = [
        (BASE + "/it/ricerca", {"s": query, "ajax": "1"}),
        (BASE + "/it/ricerca", {"search_query": query, "ajax": "1"}),
        (BASE + "/it/ricerca_old", {"s": query, "ajax": "1"}),
        (BASE + "/it/ricerca_old", {"search_query": query, "ajax": "1"}),
    ]

    for endpoint, params in endpoints:
        try:
            response = session.get(
                endpoint,
                params=params,
                headers={**HEADERS, "X-Requested-With": "XMLHttpRequest"},
                timeout=TIMEOUT,
            )
            if response.status_code in (403, 429) or not response.ok:
                response.close()
                continue
            text = response.text
            response.close()

            try:
                data = json.loads(text)
                rows = _walk_json(data, query)
                candidates = [row["url"] for row in rows]
            except Exception:
                candidates = _extract_product_links_from_html(text, query)

            for url in candidates:
                clean_url = url.split("#")[0].split("?")[0]
                if clean_url not in seen and _looks_like_product_url(clean_url):
                    seen.add(clean_url)
                    urls.append(clean_url)
        except (requests.RequestException, ValueError, TypeError):
            continue

    return urls

def _get(session, url, **kwargs):
    r = session.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True, **kwargs)
    if r.status_code in (403, 429):
        print(f"SABINA BLOCKED: HTTP {r.status_code}")
        r.close()
        return None
    r.raise_for_status()
    return r


LAST_DIAG = {}

def _diag_get(session, url, label, report, **kwargs):
    t0 = time.time()
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
            **kwargs,
        )
        rec = {
            "label": label,
            "requested_url": url,
            "final_url": response.url,
            "status": response.status_code,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content),
            "elapsed_ms": round((time.time() - t0) * 1000),
        }
        report["probes"].append(rec)
        return response, rec
    except Exception as exc:
        rec = {
            "label": label,
            "requested_url": url,
            "error": f"{type(exc).__name__}: {exc}",
        }
        report["probes"].append(rec)
        return None, rec


def _diagnostic_search(query):
    query = _clean(query)
    report = {
        "query": query,
        "tokens": _query_tokens(query),
        "probes": [],
        "stages": {},
        "candidate_urls": [],
        "verified": [],
    }

    print(f"SABINA_DIAG: START query={query!r}", flush=True)
    print(f"SABINA_DIAG: TOKENS={report['tokens']}", flush=True)

    if not query:
        report["diagnosis"] = "EMPTY_QUERY"
        LAST_DIAG = report
        return []

    session = requests.Session()
    session.headers.update(HEADERS)

    search_candidates = []
    json_candidates = []
    sitemap_candidates = []
    seen = set()

    try:
        # Stage 0: warm-up, exactly like the known-good scraper.
        response, rec = _diag_get(session, BASE + "/it/", "WARMUP_IT", report)
        if response is not None:
            response.close()
        report["stages"]["warmup"] = rec

        # Stage 1: native site-search discovery.
        try:
            search_candidates = _discover_from_search_page(session, query)
        except Exception as exc:
            report["stages"]["native_search_error"] = f"{type(exc).__name__}: {exc}"
            search_candidates = []

        for url in search_candidates:
            if url not in seen:
                seen.add(url)
        report["stages"]["native_search_candidates"] = len(search_candidates)
        print(
            f"SABINA_DIAG: NATIVE_SEARCH candidates={len(search_candidates)}",
            flush=True,
        )
        for url in search_candidates[:20]:
            print(f"SABINA_DIAG: NATIVE_CANDIDATE {url}", flush=True)

        # Stage 2: generic JSON/AJAX discovery, same code as working scraper.
        try:
            json_candidates = _discover_from_json_endpoints(session, query)
        except Exception as exc:
            report["stages"]["json_search_error"] = f"{type(exc).__name__}: {exc}"
            json_candidates = []

        report["stages"]["json_candidates"] = len(json_candidates)
        print(
            f"SABINA_DIAG: JSON_SEARCH candidates={len(json_candidates)}",
            flush=True,
        )
        for url in json_candidates[:20]:
            print(f"SABINA_DIAG: JSON_CANDIDATE {url}", flush=True)

        candidate_urls = []
        for url in search_candidates + json_candidates:
            clean_url = url.split("#", 1)[0].split("?", 1)[0]
            if clean_url not in seen:
                seen.add(clean_url)
                candidate_urls.append(clean_url)

        # Stage 3: sitemap fallback exactly as the working scraper uses it.
        if not candidate_urls:
            try:
                sitemap_candidates = _discover_from_sitemap(session, query)
            except Exception as exc:
                report["stages"]["sitemap_error"] = f"{type(exc).__name__}: {exc}"
                sitemap_candidates = []

            report["stages"]["sitemap_candidates"] = len(sitemap_candidates)
            print(
                f"SABINA_DIAG: SITEMAP_FALLBACK candidates={len(sitemap_candidates)}",
                flush=True,
            )
            for url in sitemap_candidates[:20]:
                print(f"SABINA_DIAG: SITEMAP_CANDIDATE {url}", flush=True)

            for url in sitemap_candidates:
                clean_url = url.split("#", 1)[0].split("?", 1)[0]
                if clean_url not in seen:
                    seen.add(clean_url)
                    candidate_urls.append(clean_url)
        else:
            report["stages"]["sitemap_fallback"] = "NOT_USED"

        report["candidate_urls"] = candidate_urls[:15]
        report["stages"]["total_candidates"] = len(candidate_urls)

        # Stage 4: verify the real product page, using the SAME parser
        # and validation used by the working scraper.
        results = []
        result_seen = set()

        for url in candidate_urls[:15]:
            t0 = time.time()
            try:
                response = session.get(
                    url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )

                verification = {
                    "candidate_url": url,
                    "final_url": response.url,
                    "status": response.status_code,
                    "bytes": len(response.content),
                    "elapsed_ms": round((time.time() - t0) * 1000),
                }

                if response.status_code in (403, 429):
                    verification["reason"] = f"HTTP_{response.status_code}"
                    report["verified"].append(verification)
                    print(
                        f"SABINA_DIAG: VERIFY BLOCKED status={response.status_code} url={url}",
                        flush=True,
                    )
                    response.close()
                    continue

                if not response.ok:
                    verification["reason"] = f"HTTP_{response.status_code}"
                    report["verified"].append(verification)
                    response.close()
                    continue

                html = response.text
                response.close()

                parsed = _parse_html(html, query)
                verification["parsed_items"] = len(parsed)

                if parsed:
                    verification["parsed_names"] = [
                        item.get("name", "") for item in parsed[:5]
                    ]

                report["verified"].append(verification)

                for item in parsed:
                    key = (
                        item.get("name", "").lower(),
                        item.get("url", "").split("?")[0].split("#")[0],
                        item.get("price"),
                    )
                    if key in result_seen:
                        continue
                    result_seen.add(key)
                    results.append(item)

                print(
                    f"SABINA_DIAG: VERIFY status={verification['status']} "
                    f"parsed={len(parsed)} url={url}",
                    flush=True,
                )

            except Exception as exc:
                verification = {
                    "candidate_url": url,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                report["verified"].append(verification)
                print(
                    f"SABINA_DIAG: VERIFY_ERROR {url} "
                    f"{type(exc).__name__}: {exc}",
                    flush=True,
                )

        report["stages"]["verified_pages"] = len(report["verified"])
        report["stages"]["verified_products"] = len(results)

        # Definitive diagnosis is based on the stage that actually failed.
        if results:
            diagnosis = "PRODUCT_FOUND_AND_VERIFIED"
        elif candidate_urls:
            diagnosis = "CANDIDATES_FOUND_BUT_REAL_PRODUCT_PAGE_REJECTED"
        elif search_candidates or json_candidates:
            diagnosis = "DISCOVERY_RETURNED_NO_USABLE_PRODUCT_URLS"
        elif report["stages"].get("sitemap_candidates", 0) == 0:
            diagnosis = "NO_PRODUCT_URL_DISCOVERED"
        else:
            diagnosis = "SITEMAP_DISCOVERY_RETURNED_NO_USABLE_PRODUCT_URLS"

        report["diagnosis"] = diagnosis

        print(f"SABINA_DIAGNOSIS: {diagnosis}", flush=True)
        print(
            "SABINA_DIAG_SUMMARY: "
            + json.dumps(
                {
                    "native_search_candidates": len(search_candidates),
                    "json_candidates": len(json_candidates),
                    "sitemap_candidates": len(sitemap_candidates),
                    "total_candidates": len(candidate_urls),
                    "verified_pages": len(report["verified"]),
                    "verified_products": len(results),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        print(
            "SABINA_DIAG_REPORT_BEGIN",
            flush=True,
        )
        print(
            json.dumps(report, ensure_ascii=False, indent=2),
            flush=True,
        )
        print(
            "SABINA_DIAG_REPORT_END",
            flush=True,
        )

        LAST_DIAG = report
        return results

    finally:
        session.close()


def search(query):
    # IMPORTANT: main.py requires every scraper module to expose search().
    # This diagnostic is therefore a drop-in scraper, not a standalone script.
    return _diagnostic_search(query)


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    q = " ".join(sys.argv[1:]).strip() or "Liquid brun"
    print(json.dumps(search(q), ensure_ascii=False, indent=2))
