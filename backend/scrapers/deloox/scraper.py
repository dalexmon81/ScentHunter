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
        homepage_products, homepage_categories = inspect_page(
            homepage,
            query,
            "homepage",
        )

        # 2) Execute the REAL search form discovered on Deloox.
        # The homepage already told us the canonical action is /zoeken.html
        # and the query field is q. We use the discovered form rather than
        # guessing /search or /zoeken endpoints.
        search_forms = []

        if homepage is not None and homepage.status_code == 200:
            homepage_soup = BeautifulSoup(homepage.text, "html.parser")

            for form in homepage_soup.find_all("form"):
                action = urljoin(
                    homepage.url,
                    clean(form.get("action")),
                )
                method = clean(
                    form.get("method") or "GET"
                ).upper()

                fields = [
                    clean(element.get("name"))
                    for element in form.find_all(
                        ["input", "select", "textarea"]
                    )
                    if clean(element.get("name"))
                ]

                if (
                    action.rstrip("/").endswith("/zoeken.html")
                    and "q" in fields
                ):
                    search_forms.append(
                        {
                            "action": action,
                            "method": method,
                            "fields": fields,
                        }
                    )

        log(
            f"REAL_SEARCH_FORMS count={len(search_forms)} "
            f"forms={search_forms}"
        )

        all_products = list(homepage_products)
        all_categories = list(homepage_categories)

        seen_search_forms = set()

        for form in search_forms:
            form_key = (
                form["method"],
                form["action"],
                tuple(form["fields"]),
            )

            if form_key in seen_search_forms:
                continue

            seen_search_forms.add(form_key)

            params = {
                "q": query,
            }

            if form["method"] == "POST":
                response = request(
                    session,
                    form["action"],
                    params=None,
                )
            else:
                response = request(
                    session,
                    form["action"],
                    params=params,
                )

            print_json_if_any(
                response,
                "real_search_form",
            )

            products, categories = inspect_page(
                response,
                query,
                "real_search_form",
            )

            all_products.extend(products)
            all_categories.extend(categories)

            if response is not None:
                log(
                    f"REAL_SEARCH_RESULT "
                    f"url={response.url} "
                    f"status={response.status_code} "
                    f"products={len(products)} "
                    f"categories={len(categories)}"
                )

        # Always probe the exact canonical search page as a fallback to the
        # form-discovery step. This is still generic: it uses the form action
        # and query field discovered from the site's HTML.
        if not search_forms:
            canonical_search = urljoin(
                BASE_URL,
                "/zoeken.html",
            )

            response = request(
                session,
                canonical_search,
                params={"q": query},
            )

            print_json_if_any(
                response,
                "canonical_search",
            )

            products, categories = inspect_page(
                response,
                query,
                "canonical_search",
            )

            all_products.extend(products)
            all_categories.extend(categories)

        # Inspect the inline JavaScript around the two route variables that
        # the homepage exposed. We do not execute JS; we only print the
        # surrounding source so the real API paths can be identified.
        if homepage is not None:
            source = homepage.text

            for marker in (
                "routeApiProducts",
                "routeApiFilter",
            ):
                positions = [
                    match.start()
                    for match in re.finditer(
                        re.escape(marker),
                        source,
                        re.I,
                    )
                ]

                for position in positions[:5]:
                    begin = max(0, position - 1200)
                    finish = min(
                        len(source),
                        position + 1800,
                    )

                    snippet = source[begin:finish]

                    log(
                        f"JS_ROUTE_SOURCE marker={marker} "
                        f"position={position}"
                    )
                    print(snippet, flush=True)

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
