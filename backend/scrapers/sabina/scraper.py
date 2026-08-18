import json
import re
import time
import unicodedata
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
TIMEOUT = 15

MAX_SITEMAPS = 80
MAX_PRODUCT_CANDIDATES = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,*/*;q=0.8"
    ),
}

# These are diagnostic probes only.
# The query is always supplied at runtime.
SEARCH_ENDPOINTS = (
    ("/es/buscar_old", {"s": "QUERY"}),
    ("/es/buscar", {"s": "QUERY"}),
    ("/es/buscar", {"controller": "search", "s": "QUERY"}),
    ("/es/buscar", {"search_query": "QUERY"}),
)

# This sitemap was independently observed to be the shop sitemap index.
SITEMAP_INDEX_URL = BASE_URL + "/sitemap_index_shop_1.xml"

PRODUCT_URL_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl)/[^/]+/\d+-[^/]+\.html$",
    re.I,
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(
        char for char in value
        if not unicodedata.combining(char)
    )
    value = value.lower()
    value = re.sub(
        r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)",
        " ",
        value,
    )
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query):
    ignored = {
        "eau",
        "de",
        "parfum",
        "perfume",
        "edp",
        "edt",
        "extrait",
        "spray",
        "for",
        "by",
        "ml",
    }

    return [
        token
        for token in norm(query).split()
        if token not in ignored
    ]


def same_host(url):
    host = urlparse(url).netloc.lower()
    return host in {"www.sabina.com", "sabina.com"}


def is_product_url(url):
    return bool(PRODUCT_URL_RE.match(urlparse(url).path))


def xml_urls(text):
    urls = []

    try:
        root = ET.fromstring(text)

        for element in root.iter():
            if element.tag.lower().endswith("loc") and element.text:
                urls.append(clean(element.text))

    except Exception:
        urls = re.findall(
            r"<loc>\s*(.*?)\s*</loc>",
            text,
            re.I | re.S,
        )

        urls = [clean(value) for value in urls]

    return list(dict.fromkeys(urls))


def http_get(session, url, params=None):
    started = time.time()

    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        return {
            "ok": True,
            "status": response.status_code,
            "final_url": response.url,
            "content_type": response.headers.get("content-type"),
            "bytes": len(response.content),
            "elapsed": round(time.time() - started, 3),
            "text": response.text,
            "headers": {
                "server": response.headers.get("server"),
                "cf_ray": response.headers.get("cf-ray"),
                "location": response.headers.get("location"),
            },
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed": round(time.time() - started, 3),
        }


def search_page_diagnostics(session, query):
    diagnostics = []

    for path, raw_params in SEARCH_ENDPOINTS:
        params = {
            key: (
                query
                if value == "QUERY"
                else value
            )
            for key, value in raw_params.items()
        }

        endpoint = BASE_URL + path
        result = http_get(
            session,
            endpoint,
            params=params,
        )

        item = {
            "endpoint": endpoint,
            "params": params,
            "status": result.get("status"),
            "final_url": result.get("final_url"),
            "content_type": result.get("content_type"),
            "bytes": result.get("bytes"),
            "elapsed": result.get("elapsed"),
        }

        if not result.get("ok"):
            item["error"] = result.get("error")
            diagnostics.append(item)
            continue

        html = result["text"]
        soup = BeautifulSoup(
            html,
            "html.parser",
        )

        visible_text = soup.get_text(
            " ",
            strip=True,
        )

        raw_lower = html.lower()

        product_links = []

        for anchor in soup.find_all(
            "a",
            href=True,
        ):
            absolute = urljoin(
                result["final_url"],
                anchor["href"],
            ).split("#", 1)[0]

            if (
                same_host(absolute)
                and is_product_url(absolute)
            ):
                product_links.append(absolute)

        product_links = list(
            dict.fromkeys(product_links)
        )

        item.update({
            "query_in_raw_html": (
                norm(query) in norm(html)
            ),
            "query_in_visible_text": (
                norm(query) in norm(visible_text)
            ),
            "query_token_hits": {
                token: token in norm(visible_text)
                for token in query_tokens(query)
            },
            "product_url_count": len(product_links),
            "sample_product_urls": product_links[:10],
            "challenge_markers": [
                marker
                for marker in (
                    "captcha",
                    "cloudflare",
                    "cf-chl",
                    "verify you are human",
                    "access denied",
                )
                if marker in raw_lower
            ],
            "form_actions": [
                clean(form.get("action"))
                for form in soup.find_all("form")
                if form.get("action")
            ][:20],
            "script_count": len(
                soup.find_all("script")
            ),
        })

        diagnostics.append(item)

    return diagnostics


def sitemap_diagnostics(session, query):
    result = http_get(
        session,
        SITEMAP_INDEX_URL,
    )

    info = {
        "index_url": SITEMAP_INDEX_URL,
        "status": result.get("status"),
        "content_type": result.get("content_type"),
        "bytes": result.get("bytes"),
        "elapsed": result.get("elapsed"),
        "sitemaps_seen": 0,
        "sitemaps_fetched": 0,
        "product_candidates": [],
        "errors": [],
    }

    if not result.get("ok"):
        info["error"] = result.get("error")
        return info

    if result.get("status", 0) >= 400:
        info["error"] = "sitemap_index_http_error"
        return info

    sitemap_urls = [
        url
        for url in xml_urls(result["text"])
        if url.startswith("http")
    ]

    info["sitemaps_seen"] = len(
        sitemap_urls
    )

    wanted_tokens = set(
        query_tokens(query)
    )

    candidates = []

    for sitemap_url in sitemap_urls[:MAX_SITEMAPS]:
        child = http_get(
            session,
            sitemap_url,
        )

        info["sitemaps_fetched"] += 1

        if not child.get("ok"):
            info["errors"].append({
                "url": sitemap_url,
                "error": child.get("error"),
            })
            continue

        if child.get("status", 0) >= 400:
            info["errors"].append({
                "url": sitemap_url,
                "status": child.get("status"),
            })
            continue

        urls = xml_urls(
            child["text"]
        )

        for url in urls:
            if (
                not same_host(url)
                or not is_product_url(url)
            ):
                continue

            url_normalized = norm(url)

            if (
                wanted_tokens
                and all(
                    token in url_normalized
                    for token in wanted_tokens
                )
            ):
                candidates.append(
                    url.split("#", 1)[0]
                )

        candidates = list(
            dict.fromkeys(candidates)
        )

        if candidates:
            break

    info["product_candidates"] = candidates[
        :MAX_PRODUCT_CANDIDATES
    ]

    return info


def extract_jsonld_products(soup):
    products = []

    for script in soup.find_all(
        "script",
        attrs={
            "type": re.compile(
                r"application/ld\+json",
                re.I,
            )
        },
    ):
        raw = (
            script.string
            or script.get_text()
        )

        if not raw:
            continue

        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = (
            data
            if isinstance(data, list)
            else [data]
        )

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            item_type = item.get("@type")

            types = (
                item_type
                if isinstance(item_type, list)
                else [item_type]
            )

            if any(
                str(value).lower() == "product"
                for value in types
            ):
                products.append(item)

            if isinstance(
                item.get("@graph"),
                list,
            ):
                stack.extend(
                    item["@graph"]
                )

    return products


def product_probe(session, url, query):
    result = http_get(
        session,
        url,
    )

    item = {
        "url": url,
        "status": result.get("status"),
        "final_url": result.get("final_url"),
        "bytes": result.get("bytes"),
        "elapsed": result.get("elapsed"),
    }

    if not result.get("ok"):
        item["error"] = result.get("error")
        return item

    soup = BeautifulSoup(
        result["text"],
        "html.parser",
    )

    h1_node = soup.select_one("h1")

    h1 = (
        clean(
            h1_node.get_text(
                " ",
                strip=True,
            )
        )
        if h1_node
        else ""
    )

    title = (
        clean(
            soup.title.get_text(
                " ",
                strip=True,
            )
        )
        if soup.title
        else ""
    )

    products = extract_jsonld_products(
        soup
    )

    jsonld_names = [
        clean(product.get("name"))
        for product in products
        if product.get("name")
    ]

    page_text = soup.get_text(
        " ",
        strip=True,
    )

    identity = norm(
        " ".join(
            [
                h1,
                title,
                *jsonld_names,
            ]
        )
    )

    item.update({
        "h1": h1,
        "title": title,
        "jsonld_product_count": len(products),
        "jsonld_names": jsonld_names[:10],
        "query_matches_identity": all(
            token in identity
            for token in query_tokens(query)
        ),
        "has_euro_price": bool(
            re.search(
                r"\d+[,.]\d{2}\s*€",
                page_text,
            )
        ),
        "reference_hits": re.findall(
            r"(?:referencia|reference|référence|riferimento)"
            r"\s*[:#]?\s*([A-Z0-9_-]+)",
            page_text,
            re.I,
        )[:10],
    })

    return item


def diagnose(query):
    query = clean(query)

    if not query:
        return {
            "store": "sabina",
            "query": "",
            "verdict": "INVALID_QUERY",
            "diagnosis": "Query vuota.",
        }

    session = requests.Session()

    search_results = search_page_diagnostics(
        session,
        query,
    )

    sitemap_result = sitemap_diagnostics(
        session,
        query,
    )

    product_probes = [
        product_probe(
            session,
            url,
            query,
        )
        for url in sitemap_result.get(
            "product_candidates",
            [],
        )
    ]

    search_has_product_links = any(
        item.get("product_url_count", 0) > 0
        for item in search_results
    )

    search_has_query = any(
        item.get("query_in_raw_html")
        or item.get("query_in_visible_text")
        for item in search_results
    )

    sitemap_has_candidates = bool(
        sitemap_result.get(
            "product_candidates"
        )
    )

    product_valid = any(
        item.get(
            "query_matches_identity"
        )
        for item in product_probes
    )

    if (
        sitemap_has_candidates
        and product_valid
        and not search_has_query
    ):
        verdict = (
            "DISCOVERY_SEARCH_BROKEN_SITEMAP_WORKS"
        )

        diagnosis = (
            "La ricerca HTTP di Sabina non espone "
            "la query/il risultato in modo utilizzabile "
            "dal parser, mentre il sitemap contiene un "
            "URL prodotto compatibile e la pagina prodotto "
            "conferma l'identità. Il problema è quindi "
            "nella discovery tramite ricerca, non nel parsing "
            "della pagina prodotto."
        )

    elif (
        sitemap_has_candidates
        and not product_valid
    ):
        verdict = (
            "DISCOVERY_FOUND_VALIDATION_FAILED"
        )

        diagnosis = (
            "Il sitemap ha prodotto candidati compatibili, "
            "ma la pagina prodotto non ha superato la "
            "validazione dell'identità."
        )

    elif search_has_product_links:
        verdict = "SEARCH_HTML_USABLE"

        diagnosis = (
            "La risposta HTML della ricerca espone URL "
            "prodotto. Il problema va cercato nell'estrazione "
            "o nella validazione dei candidati."
        )

    else:
        verdict = "INCONCLUSIVE"

        diagnosis = (
            "Nessuna delle fonti HTTP testate ha prodotto "
            "un candidato prodotto validato. Il report "
            "completo indica esattamente quale fase non ha "
            "risposto."
        )

    return {
        "diagnostic_version": (
            "sabina-DIAGNOSTIC-FINAL-1"
        ),
        "store": "sabina",
        "query": query,
        "verdict": verdict,
        "diagnosis": diagnosis,
        "search": search_results,
        "sitemap": sitemap_result,
        "product_probes": product_probes,
        "method": (
            "HTTP_SEARCH_PLUS_SITEMAP_PLUS_"
            "PRODUCT_VALIDATION"
        ),
    }


def search(query):
    """
    Compatibilità con main.py.

    Il file è intenzionalmente un diagnostico: restituisce
    un solo risultato contenente il report completo.
    Non contiene eccezioni basate su prodotti specifici.
    """
    diagnostic = diagnose(query)

    return [{
        "store": STORE,
        "name": (
            f"SABINA_DIAGNOSTIC "
            f"{clean(query)}"
        ),
        "brand": "Sabina",
        "price": "diagnostic",
        "url": BASE_URL,
        "available": False,
        "raw_data": diagnostic,
    }]


scrape = search


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Sabina definitive HTTP discovery diagnostic"
        )
    )

    parser.add_argument(
        "query",
        help="Query supplied at runtime",
    )

    args = parser.parse_args()

    report = diagnose(
        args.query
    )

    print(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        )
    )
