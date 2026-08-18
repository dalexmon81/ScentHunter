import json
import re
import time
import unicodedata
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
}

# Sabina product URLs are numeric product routes. This is intentionally
# generic and contains no product/brand-specific rule.
PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl|pt)/[^/]+/(\d+)-[^/]+\.html$",
    re.I,
)

IGNORED_QUERY_WORDS = {
    "eau", "de", "parfum", "perfume", "edp", "edt",
    "extrait", "spray", "for", "by", "ml", "pour",
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query):
    return [
        token for token in norm(query).split()
        if token not in IGNORED_QUERY_WORDS
    ]


def text_matches(text, query):
    tokens = query_tokens(query)
    normalized = norm(text)
    return bool(tokens) and all(token in normalized for token in tokens)


def is_product_url(url):
    return bool(PRODUCT_PATH_RE.match(urlparse(url).path))


def product_id(url):
    match = PRODUCT_PATH_RE.match(urlparse(url).path)
    return match.group(1) if match else None


def request_page(session, url, params=None):
    started = time.monotonic()
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        elapsed = round(time.monotonic() - started, 3)
        return {
            "ok": response.status_code < 400,
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type", ""),
            "bytes": len(response.content),
            "elapsed": elapsed,
            "html": response.text,
            "error": None,
        }
    except requests.RequestException as exc:
        elapsed = round(time.monotonic() - started, 3)
        return {
            "ok": False,
            "status": None,
            "final_url": None,
            "content_type": "",
            "bytes": 0,
            "elapsed": elapsed,
            "html": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def extract_product_links(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        absolute = urljoin(base_url, anchor["href"]).split("#")[0]

        if not is_product_url(absolute):
            continue

        path = urlparse(absolute).path
        if path in seen:
            continue

        seen.add(path)

        visible = clean(
            anchor.get("title")
            or anchor.get("aria-label")
            or anchor.get_text(" ", strip=True)
        )

        parent_text = visible
        parent = anchor
        for _ in range(4):
            parent = parent.parent if parent is not None else None
            if parent is None:
                break
            candidate = clean(parent.get_text(" ", strip=True))
            if len(candidate) > len(parent_text):
                parent_text = candidate

        found.append({
            "url": absolute,
            "id": product_id(absolute),
            "anchor_text": visible[:300],
            "nearby_text": parent_text[:1000],
            "query_match_in_link_context": None,
        })

    return found


def find_query_hits(candidates, query):
    hits = []

    for item in candidates:
        context = (
            item.get("anchor_text", "")
            + " "
            + item.get("nearby_text", "")
        )

        if text_matches(context, query):
            item = dict(item)
            item["query_match_in_link_context"] = True
            hits.append(item)
        else:
            item = dict(item)
            item["query_match_in_link_context"] = False

    return hits


def extract_form_actions(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    actions = []

    for form in soup.find_all("form", action=True):
        action = urljoin(base_url, form.get("action"))
        if action not in actions:
            actions.append(action)

    return actions[:30]


def extract_script_count(html):
    return len(BeautifulSoup(html, "html.parser").find_all("script"))


def probe_product_page(session, url, query):
    result = request_page(session, url)

    probe = {
        "url": url,
        "id": product_id(url),
        "request": {
            key: result[key]
            for key in (
                "status", "final_url", "content_type",
                "bytes", "elapsed", "error"
            )
        },
        "valid": False,
        "title": "",
        "brand": "",
        "query_match_in_product_page": False,
        "jsonld_product": False,
        "jsonld_name": "",
        "price": None,
    }

    if not result["ok"]:
        return probe

    soup = BeautifulSoup(result["html"], "html.parser")

    h1 = soup.select_one("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else ""

    probe["title"] = title
    probe["query_match_in_product_page"] = text_matches(
        title + " " + soup.get_text(" ", strip=True),
        query,
    )

    # JSON-LD is inspected only as evidence; it is not required for
    # discovery to succeed.
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue

        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            if isinstance(item.get("@graph"), list):
                stack.extend(item["@graph"])

            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]

            if any(str(t).lower() == "product" for t in types):
                probe["jsonld_product"] = True
                probe["jsonld_name"] = clean(item.get("name"))

                brand = item.get("brand")
                if isinstance(brand, dict):
                    probe["brand"] = clean(brand.get("name"))
                else:
                    probe["brand"] = clean(brand)

                offers = item.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict):
                    probe["price"] = offers.get("price")

                break

    probe["valid"] = bool(
        probe["query_match_in_product_page"]
        and probe["title"]
    )

    return probe


def sitemap_discovery(session, query):
    result = {
        "index_url": BASE_URL + "/sitemap_index.xml",
        "status": None,
        "content_type": "",
        "bytes": 0,
        "sitemaps_seen": 0,
        "sitemaps_fetched": 0,
        "product_candidates": [],
        "errors": [],
    }

    first = request_page(session, result["index_url"])

    result["status"] = first["status"]
    result["content_type"] = first["content_type"]
    result["bytes"] = first["bytes"]

    if not first["ok"]:
        result["errors"].append(first["error"] or "sitemap index unavailable")
        return result

    soup = BeautifulSoup(first["html"], "xml")
    sitemap_urls = []

    for loc in soup.find_all("loc"):
        value = clean(loc.get_text())
        if value:
            sitemap_urls.append(value)

    result["sitemaps_seen"] = len(sitemap_urls)

    # Discovery diagnostic stays bounded. We inspect sitemap XML only;
    # no uncontrolled site crawl is performed.
    for sitemap_url in sitemap_urls[:20]:
        sm = request_page(session, sitemap_url)
        if not sm["ok"]:
            result["errors"].append({
                "url": sitemap_url,
                "error": sm["error"] or f"HTTP {sm['status']}",
            })
            continue

        result["sitemaps_fetched"] += 1

        sm_soup = BeautifulSoup(sm["html"], "xml")
        for loc in sm_soup.find_all("loc"):
            candidate = clean(loc.get_text())
            if not candidate or not is_product_url(candidate):
                continue

            if text_matches(candidate, query):
                result["product_candidates"].append(candidate)

            if len(result["product_candidates"]) >= 20:
                break

        if len(result["product_candidates"]) >= 20:
            break

    result["product_candidates"] = list(dict.fromkeys(
        result["product_candidates"]
    ))

    return result


def discovery_diagnostic(query):
    query = clean(query)
    if not query:
        return {
            "diagnostic_version": "sabina-discovery-diagnostic-1",
            "store": STORE,
            "query": "",
            "verdict": "EMPTY_QUERY",
            "diagnosis": "La query è vuota.",
        }

    session = requests.Session()

    # These are intentionally different discovery mechanisms. The diagnostic
    # must show which mechanism actually discovers product URLs.
    endpoints = [
        {
            "name": "SEARCH_QUERY",
            "url": BASE_URL + "/es/buscar",
            "params": {"search_query": query},
        },
        {
            "name": "SEARCH_S",
            "url": BASE_URL + "/es/buscar",
            "params": {"s": query},
        },
        {
            "name": "SEARCH_CONTROLLER_S",
            "url": BASE_URL + "/es/buscar",
            "params": {"controller": "search", "s": query},
        },
        {
            "name": "SEARCH_CONTROLLER_SEARCH_QUERY",
            "url": BASE_URL + "/es/buscar",
            "params": {
                "controller": "search",
                "search_query": query,
            },
        },
    ]

    search_attempts = []

    all_candidate_urls = []
    all_query_hit_urls = []

    for endpoint in endpoints:
        result = request_page(
            session,
            endpoint["url"],
            endpoint["params"],
        )

        html = result["html"]

        candidates = extract_product_links(
            html,
            result["final_url"] or endpoint["url"],
        )

        query_hits = find_query_hits(candidates, query)

        # Also inspect raw HTML text. This distinguishes a result that is
        # present only in markup from one whose visible search cards contain it.
        raw_query_match = text_matches(html, query)
        visible_query_match = text_matches(
            BeautifulSoup(html, "html.parser").get_text(" ", strip=True),
            query,
        )

        attempt = {
            "name": endpoint["name"],
            "endpoint": endpoint["url"],
            "params": endpoint["params"],
            "status": result["status"],
            "final_url": result["final_url"],
            "content_type": result["content_type"],
            "bytes": result["bytes"],
            "elapsed": result["elapsed"],
            "query_in_raw_html": raw_query_match,
            "query_in_visible_text": visible_query_match,
            "query_token_hits": {
                token: token in norm(html)
                for token in query_tokens(query)
            },
            "product_url_count": len(candidates),
            "query_product_url_count": len(query_hits),
            "sample_product_urls": [
                item["url"] for item in candidates[:10]
            ],
            "sample_query_product_urls": [
                item["url"] for item in query_hits[:10]
            ],
            "form_actions": extract_form_actions(
                html,
                result["final_url"] or endpoint["url"],
            ),
            "script_count": extract_script_count(html),
            "error": result["error"],
        }

        search_attempts.append(attempt)

        for item in candidates:
            all_candidate_urls.append(item["url"])

        for item in query_hits:
            all_query_hit_urls.append(item["url"])

    all_candidate_urls = list(dict.fromkeys(all_candidate_urls))
    all_query_hit_urls = list(dict.fromkeys(all_query_hit_urls))

    # Sitemap is independent evidence. It is useful when the site's search
    # endpoint is broken but the product is publicly indexed.
    sitemap = sitemap_discovery(session, query)

    # Product validation is done against actual product pages, not against
    # search-card text alone.
    probe_urls = list(dict.fromkeys(
        all_query_hit_urls + sitemap["product_candidates"]
    ))[:12]

    product_probes = [
        probe_product_page(session, url, query)
        for url in probe_urls
    ]

    valid_products = [
        probe for probe in product_probes
        if probe["valid"]
    ]

    winning_search = [
        attempt for attempt in search_attempts
        if attempt["query_product_url_count"] > 0
    ]

    if valid_products:
        verdict = "DISCOVERY_WORKS"
        diagnosis = (
            "La discovery raggiunge URL prodotto reali e la validazione "
            "della pagina prodotto conferma la query."
        )
    elif all_query_hit_urls:
        verdict = "DISCOVERY_FINDS_URL_BUT_VALIDATION_FAILS"
        diagnosis = (
            "La discovery trova URL prodotto compatibili, ma la validazione "
            "delle pagine prodotto non conferma la query."
        )
    elif any(
        attempt["product_url_count"] > 0
        for attempt in search_attempts
    ):
        verdict = "SEARCH_RETURNS_PRODUCTS_BUT_QUERY_MATCH_IS_WRONG"
        diagnosis = (
            "Sabina restituisce URL prodotto, ma il collegamento tra la "
            "query e i candidati è il punto da correggere."
        )
    elif sitemap["product_candidates"]:
        verdict = "SITEMAP_DISCOVERY_ONLY"
        diagnosis = (
            "La discovery via sitemap trova candidati, mentre i percorsi "
            "di ricerca HTML non stanno trovando candidati validi."
        )
    else:
        verdict = "NO_DISCOVERY_PATH_FOUND"
        diagnosis = (
            "Nessun percorso testato ha prodotto un candidato utile. "
            "Il diagnostico deve essere esteso solo dopo aver visto questi dati."
        )

    return {
        "diagnostic_version": "sabina-discovery-diagnostic-1",
        "store": STORE,
        "query": query,
        "verdict": verdict,
        "diagnosis": diagnosis,
        "search": {
            "attempts": search_attempts,
            "winning_endpoints": winning_search,
            "all_query_product_urls": all_query_hit_urls,
        },
        "sitemap": sitemap,
        "product_probes": product_probes,
        "valid_product_count": len(valid_products),
        "method": "HTTP_SEARCH_ENDPOINTS_PLUS_SITEMAP_PLUS_PRODUCT_VALIDATION",
    }


def search(query):
    diagnostic = discovery_diagnostic(query)

    # /test-store expects a list of products. The diagnostic is deliberately
    # returned as one result so the existing test endpoint can display all
    # evidence under raw_data without changing main.py.
    return [{
        "store": STORE,
        "source": {
            "url": BASE_URL,
            "name": f"SABINA_DISCOVERY_DIAGNOSTIC {query}",
            "brand": STORE,
            "image": "",
        },
        "identity": {},
        "attributes": {},
        "offer": {
            "price": None,
            "currency": "EUR",
            "availability": "unknown",
        },
        "provenance": {
            "name": "diagnostic",
            "brand": "diagnostic",
        },
        "raw_data": diagnostic,

        # Backward-compatible fields required by the current main.py.
        "name": f"SABINA_DISCOVERY_DIAGNOSTIC {query}",
        "brand": STORE,
        "price": "diagnostic",
        "url": BASE_URL,
        "available": False,
    }]


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Sabina discovery diagnostic"
    )
    parser.add_argument(
        "query",
        help="Query runtime da diagnosticare",
    )
    args = parser.parse_args()

    print(
        json.dumps(
            discovery_diagnostic(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
