import json
import re
from urllib.parse import urljoin, quote_plus, urlparse

import requests
from bs4 import BeautifulSoup


STORE = "Deloox"
BASE_URL = "https://www.deloox.nl"
TIMEOUT = 15
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

PRODUCT_RE = re.compile(
    r"/(?:product|producto|produit|produkt)/(\d+)/",
    re.I,
)

CATEGORY_RE = re.compile(
    r"/(?:categorie|category|categoria|catégorie|kategorie)/",
    re.I,
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = clean(value).lower()
    value = re.sub(r"[^a-z0-9À-ÿ]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def same_host(url):
    try:
        return urlparse(url).netloc.lower().endswith("deloox.nl")
    except Exception:
        return False


def kind(url):
    if PRODUCT_RE.search(url or ""):
        return "PRODUCT"
    if CATEGORY_RE.search(url or ""):
        return "CATEGORY"
    return "OTHER"


def log(message):
    print(f"DELOOX_DIAGNOSTIC | {message}", flush=True)


def request(session, url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        log(
            f"HTTP status={response.status_code} "
            f"requested={url} "
            f"final={response.url} "
            f"type={response.headers.get('content-type', '')} "
            f"bytes={len(response.content)}"
        )

        return response

    except requests.RequestException as exc:
        log(f"HTTP_ERROR url={url} error={type(exc).__name__}: {exc}")
        return None


def print_json_if_any(response, label):
    if response is None:
        return

    content_type = response.headers.get("content-type", "").lower()

    # Try JSON regardless of content-type because some endpoints return JSON
    # with an HTML-ish content type.
    try:
        data = response.json()
    except (ValueError, TypeError):
        return

    if isinstance(data, dict):
        keys = list(data.keys())
        log(f"JSON label={label} keys={keys[:40]}")
    else:
        log(f"JSON label={label} type={type(data).__name__}")

    raw = response.text
    if len(raw) > 12000:
        raw = raw[:12000] + "\n...[JSON TRUNCATED]"

    log(f"JSON_BEGIN label={label}")
    print(raw, flush=True)
    log(f"JSON_END label={label}")


def extract_links(soup, page_url, query):
    query_n = norm(query)
    query_tokens = [x for x in query_n.split() if len(x) > 1]

    products = []
    categories = []
    seen_products = set()
    seen_categories = set()

    for anchor in soup.find_all("a", href=True):
        href = clean(anchor.get("href"))
        url = urljoin(page_url, href).split("?")[0]

        if not same_host(url):
            continue

        text = clean(
            anchor.get("title")
            or anchor.get("aria-label")
            or anchor.get_text(" ", strip=True)
        )

        haystack = norm(f"{text} {url}")
        score = sum(token in haystack for token in query_tokens)

        url_kind = kind(url)

        if url_kind == "PRODUCT":
            if url not in seen_products:
                seen_products.add(url)
                products.append((score, text, url))

        elif url_kind == "CATEGORY":
            if score > 0 and url not in seen_categories:
                seen_categories.add(url)
                categories.append((score, text, url))

    products.sort(reverse=True, key=lambda x: x[0])
    categories.sort(reverse=True, key=lambda x: x[0])

    return products, categories


def inspect_page(response, query, label):
    if response is None or response.status_code != 200:
        return [], []

    soup = BeautifulSoup(response.text, "html.parser")

    products, categories = extract_links(
        soup,
        response.url,
        query,
    )

    log(
        f"PAGE label={label} "
        f"title={clean(soup.title.get_text()) if soup.title else ''!r} "
        f"products={len(products)} categories={len(categories)}"
    )

    for product_entry in products[:25]:
        score = product_entry[0]
        text = product_entry[1]
        url = product_entry[2]
        log(
            f"PRODUCT_CANDIDATE label={label} score={score} "
            f"text={text[:180]!r} url={url}"
        )

    for category_entry in categories[:15]:
        score = category_entry[0]
        text = category_entry[1]
        url = category_entry[2]
        log(
            f"CATEGORY_CANDIDATE label={label} score={score} "
            f"text={text[:180]!r} url={url}"
        )

    # Search for forms and JS endpoint hints.
    for form in soup.find_all("form"):
        action = urljoin(response.url, clean(form.get("action")))
        fields = [
            clean(x.get("name"))
            for x in form.find_all(["input", "select", "textarea"])
            if clean(x.get("name"))
        ]

        if (
            "search" in action.lower()
            or "zoek" in action.lower()
            or any(
                x.lower() in {"q", "query", "search", "zoek"}
                for x in fields
            )
        ):
            log(
                f"SEARCH_FORM label={label} method={clean(form.get('method') or 'GET').upper()} "
                f"action={action} fields={fields}"
            )

    scripts = []
    for script in soup.find_all("script", src=True):
        src = urljoin(response.url, clean(script.get("src")))
        if same_host(src):
            scripts.append(src)

    log(
        f"SCRIPTS label={label} count={len(scripts)} "
        f"first={scripts[:20]}"
    )

    # Generic endpoint hints in inline JavaScript.
    inline = "\n".join(
        script.get_text()
        for script in soup.find_all("script")
        if not script.get("src")
    )

    hints = set()

    patterns = [
        r"""["']([^"']*(?:search|zoek|suggest|autocomplete|api|ajax)[^"']*)["']""",
        r"""fetch\(\s*["']([^"']+)["']""",
        r"""axios\.(?:get|post)\(\s*["']([^"']+)["']""",
    ]

    for pattern in patterns:
        for value in re.findall(pattern, inline, re.I):
            value = clean(value)
            if value:
                hints.add(value)

    if hints:
        log(f"JS_ENDPOINT_HINTS label={label} hints={sorted(hints)[:100]}")

    return products, categories


def inspect_search_route(session, query, path, params, label):
    response = request(
        session,
        urljoin(BASE_URL, path),
        params=params,
    )

    print_json_if_any(response, label)

    products, categories = inspect_page(
        response,
        query,
        label,
    )

    return response, products, categories


def search(query):
    """
    TEMPORARY DIAGNOSTIC ONLY.

    This version intentionally returns no Deloox results. Its sole purpose is
    to let the normal ScentHunter search execute the Deloox request flow and
    write the discovery evidence into the backend logs.

    No product-specific rule, seed, URL or exception is used.
    """
    query = clean(query)

    if not query:
        return []

    log(f"START query={query!r}")

    session = requests.Session()

    try:
        # 1) Homepage.
        homepage = request(
            session,
            BASE_URL + "/",
        )

        print_json_if_any(homepage, "homepage")
        _, homepage_products, homepage_categories = inspect_page(
            homepage,
            query,
            "homepage",
        )

        # 2) Generic search probes. These are diagnostic probes only.
        routes = [
            ("/search", {"q": query}, "search_q"),
            ("/search", {"query": query}, "search_query"),
            ("/zoeken", {"q": query}, "zoeken_q"),
            ("/zoeken", {"query": query}, "zoeken_query"),
            ("/catalogsearch/result/", {"q": query}, "catalogsearch_q"),
        ]

        all_products = list(homepage_products)
        all_categories = list(homepage_categories)

        for route in routes:
            path = route[0]
            params = route[1]
            label = route[2]

            response, products, categories = inspect_search_route(
                session,
                query,
                path,
                params,
                label,
            )

            all_products.extend(products)
            all_categories.extend(categories)

            # If a route redirected to a new page, inspect that final page
            # only; do not recursively crawl its internal links.
            if (
                response is not None
                and response.url.rstrip("/") != urljoin(BASE_URL, path).rstrip("/")
            ):
                log(
                    f"REDIRECT_ROUTE label={label} "
                    f"final={response.url} "
                    f"kind={kind(response.url)}"
                )

        # 3) If a category page is discovered, inspect only the first few
        # matching category URLs. This is the controlled diagnostic path.
        category_urls = []
        seen = set()

        ranked_categories = sorted(
            all_categories,
            reverse=True,
            key=lambda x: x[0],
        )

        for category_entry in ranked_categories:
            url = category_entry[2]
            if url not in seen:
                seen.add(url)
                category_urls.append(url)

        log(
            f"SUMMARY categories={len(category_urls)} "
            f"products_from_search_pages={len(all_products)}"
        )

        for index, category_url in enumerate(category_urls[:5], 1):
            response = request(
                session,
                category_url,
            )

            print_json_if_any(
                response,
                f"category_{index}",
            )

            products, categories = inspect_page(
                response,
                query,
                f"category_{index}",
            )

            log(
                f"CATEGORY_RESULT index={index} "
                f"url={category_url} "
                f"products={len(products)}"
            )

            for product_entry in products[:20]:
                score = product_entry[0]
                text = product_entry[1]
                product_url = product_entry[2]
                log(
                    f"CATEGORY_PRODUCT index={index} score={score} "
                    f"text={text[:180]!r} url={product_url}"
                )

        log("END")
        return []

    except Exception as exc:
        log(
            f"DIAGNOSTIC_EXCEPTION type={type(exc).__name__} "
            f"message={exc}"
        )
        import traceback
        traceback.print_exc()
        return []

    finally:
        session.close()


def scrape(query):
    return search(query)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    args = parser.parse_args()

    print(
        json.dumps(
            search(args.query),
            ensure_ascii=False,
            indent=2,
        )
    )
