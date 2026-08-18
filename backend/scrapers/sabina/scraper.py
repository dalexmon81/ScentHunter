import json
import re
import time
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Sabina"
BASE = "https://www.sabina.com"
TIMEOUT = 5
MAX_SEARCH_REQUESTS = 8
MAX_PRODUCT_REQUESTS = 5

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/18.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.7",
    "Accept": (
        "text/html,application/xhtml+xml,application/json;"
        "q=0.9,*/*;q=0.8"
    ),
    "Referer": BASE + "/it/",
}

PRODUCT_RE = re.compile(
    r"^https?://(?:www\.)?sabina\.com/"
    r"(?:it|fr|en|es|de|pt)/"
    r"(?!content|ricerca|ricerca_old|marchi|negozi|contatto|faq|"
    r"carrello|ordine|stato-ordine|il-mio-conto|module)"
    r"[^?#]+",
    re.I,
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_product_url(url):
    return bool(PRODUCT_RE.match(str(url or "")))


def product_links(html, base_url, query):
    soup = BeautifulSoup(html or "", "html.parser")
    tokens = [
        x for x in re.findall(r"[a-z0-9à-ÿ]+", clean(query).lower())
        if len(x) > 1
    ]

    found = []
    seen = set()

    def add(raw, source):
        url = urljoin(base_url, str(raw or "")).split("#", 1)[0].split("?", 1)[0]
        if not is_product_url(url) or url in seen:
            return
        hay = url.lower().replace("-", " ")
        # Discovery diagnostic: URL must only be structurally a product URL.
        # Query matching is reported separately and never blocks discovery.
        seen.add(url)
        found.append({
            "url": url,
            "source": source,
            "url_query_match": bool(tokens and all(t in hay for t in tokens)),
        })

    for a in soup.find_all("a", href=True):
        add(a.get("href"), "anchor")

    decoded = (html or "").replace("\\/", "/").replace("\\u002F", "/")
    for m in re.finditer(
        r'https?://(?:www\.)?sabina\.com/(?:it|fr|en|es|de|pt)/[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(m.group(0), "raw_html_absolute")

    for m in re.finditer(
        r'/(?:it|fr|en|es|de|pt)/[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(m.group(0), "raw_html_relative")

    return found


def request_step(session, label, url, params=None, method="GET"):
    started = time.monotonic()
    try:
        if method == "POST":
            response = session.post(
                url, data=params, headers=HEADERS,
                timeout=TIMEOUT, allow_redirects=True,
            )
        else:
            response = session.get(
                url, params=params, headers=HEADERS,
                timeout=TIMEOUT, allow_redirects=True,
            )

        elapsed = round(time.monotonic() - started, 3)
        html = response.text or ""

        return {
            "label": label,
            "method": method,
            "url": response.url,
            "requested_url": url,
            "params": params or {},
            "status": response.status_code,
            "elapsed_seconds": elapsed,
            "bytes": len(response.content),
            "content_type": response.headers.get("content-type", ""),
            "redirected": response.url != response.request.url,
            "error": None,
            "html": html,
        }
    except Exception as exc:
        return {
            "label": label,
            "method": method,
            "url": None,
            "requested_url": url,
            "params": params or {},
            "status": None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "bytes": 0,
            "content_type": "",
            "redirected": False,
            "error": f"{type(exc).__name__}: {exc}",
            "html": "",
        }


def run_diagnostic(query):
    query = clean(query)
    session = requests.Session()
    session.headers.update(HEADERS)

    report = {
        "diagnostic": "SABINA_DISCOVERY_TRACE_FINAL",
        "store": STORE,
        "query": query,
        "limits": {
            "max_search_requests": MAX_SEARCH_REQUESTS,
            "max_product_requests": MAX_PRODUCT_REQUESTS,
            "timeout_seconds_per_request": TIMEOUT,
        },
        "steps": [],
        "candidate_urls": [],
        "product_checks": [],
        "verdict": {},
    }

    # EXACTLY the discovery families that matter. No AJAX loops,
    # no Google/Bing, no sitemap crawl, no unbounded fallback.
    endpoints = [
        ("homepage", BASE + "/it/", None, "GET"),
        (
            "modern_search_query",
            BASE + "/es/buscar",
            {"search_query": query},
            "GET",
        ),
        (
            "modern_search_s",
            BASE + "/es/buscar",
            {"s": query},
            "GET",
        ),
        (
            "legacy_search_s",
            BASE + "/es/buscar_old",
            {"s": query},
            "GET",
        ),
        (
            "legacy_search_query",
            BASE + "/es/buscar_old",
            {"search_query": query},
            "GET",
        ),
        (
            "legacy_controller_search",
            BASE + "/es/buscar_old",
            {"controller": "search", "s": query},
            "GET",
        ),
        (
            "italian_search_s",
            BASE + "/it/ricerca",
            {"s": query},
            "GET",
        ),
        (
            "italian_search_query",
            BASE + "/it/ricerca",
            {"search_query": query},
            "GET",
        ),
    ]

    for index, (label, url, params, method) in enumerate(
        endpoints[:MAX_SEARCH_REQUESTS],
        start=1,
    ):
        step = request_step(session, label, url, params, method)
        html = step.pop("html")

        links = product_links(html, step["url"] or url, query)

        visible = clean(
            BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        )

        step["query_in_raw_html"] = clean(query).lower() in html.lower()
        step["query_in_visible_text"] = clean(query).lower() in visible.lower()
        step["product_url_count"] = len(links)
        step["query_matching_product_urls"] = [
            x["url"] for x in links if x["url_query_match"]
        ]
        step["sample_product_urls"] = [
            x["url"] for x in links[:10]
        ]
        step["block_signals"] = [
            token for token in (
                "captcha", "cloudflare", "access denied",
                "forbidden", "verify you are human",
            )
            if token in html.lower()
        ]

        report["steps"].append(step)

        for item in links:
            if item["url"] not in report["candidate_urls"]:
                report["candidate_urls"].append(item["url"])

    # Only probe a few candidates. The purpose is to identify the blocking
    # stage, not to scrape the store.
    for url in report["candidate_urls"][:MAX_PRODUCT_REQUESTS]:
        step = request_step(
            session,
            "product_page",
            url,
            None,
            "GET",
        )
        html = step.pop("html")

        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")
        title = clean(h1.get_text(" ", strip=True)) if h1 else ""

        jsonld_products = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                data = json.loads(script.get_text(strip=True))
            except Exception:
                continue

            stack = data if isinstance(data, list) else [data]
            while stack:
                obj = stack.pop()
                if isinstance(obj, list):
                    stack.extend(obj)
                elif isinstance(obj, dict):
                    typ = obj.get("@type")
                    types = typ if isinstance(typ, list) else [typ]
                    if any(str(t).lower() == "product" for t in types):
                        jsonld_products.append(clean(obj.get("name")))

        step["title"] = title
        step["jsonld_product"] = bool(jsonld_products)
        step["jsonld_names"] = jsonld_products[:5]
        step["query_match_title"] = (
            clean(query).lower() in title.lower()
            if title else False
        )
        report["product_checks"].append(step)

    discovery_candidates = len(report["candidate_urls"])
    successful_searches = [
        x for x in report["steps"]
        if x.get("status") == 200 and x.get("bytes", 0) > 0
    ]
    valid_products = [
        x for x in report["product_checks"]
        if x.get("status") == 200
        and x.get("jsonld_product")
    ]

    if valid_products:
        verdict = "DISCOVERY_AND_PRODUCT_ACCESS_WORK"
        reason = "URL prodotto scoperti e pagine prodotto accessibili."
    elif discovery_candidates:
        verdict = "DISCOVERY_WORKS_PRODUCT_STAGE_FAILS"
        reason = "La discovery trova URL, ma il problema è dopo la discovery."
    elif successful_searches:
        verdict = "SEARCH_RESPONSE_WORKS_DISCOVERY_FAILS"
        reason = (
            "Le pagine di ricerca rispondono, ma nessuna espone URL prodotto "
            "nel percorso analizzato."
        )
    else:
        verdict = "SEARCH_ACCESS_FAILS"
        reason = "Le richieste di ricerca non restituiscono una risposta utilizzabile."

    report["verdict"] = {
        "stage": verdict,
        "reason": reason,
        "candidate_count": discovery_candidates,
        "valid_product_page_count": len(valid_products),
        "search_response_count": len(successful_searches),
        "total_requests": (
            len(report["steps"]) + len(report["product_checks"])
        ),
    }

    session.close()
    return report


def search(query):
    # Diagnostic output is wrapped in the normal ScentHunter shape so
    # /test-store can display the complete report without changing main.py.
    report = run_diagnostic(query)
    return [{
        "store": STORE,
        "name": "SABINA_DISCOVERY_TRACE",
        "brand": STORE,
        "price": 0.0,
        "url": BASE,
        "available": False,
        "source": {
            "url": BASE,
            "name": "SABINA_DISCOVERY_TRACE",
            "brand": STORE,
            "image": None,
        },
        "identity": {},
        "attributes": {},
        "offer": {
            "price": 0.0,
            "currency": "EUR",
            "availability": "diagnostic",
        },
        "provenance": {"diagnostic": True},
        "raw_data": report,
    }]


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Sabina discovery trace"
    )
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            run_diagnostic(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
