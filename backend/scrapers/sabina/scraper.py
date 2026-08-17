import re
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup


BASE = "https://www.sabina.com"

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)

HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/fr/",
}

TIMEOUT = 15

# Generic catalog entry points only.
# No perfume, product, or brand URL is hard-coded.
ROOTS = (
    BASE + "/fr/",
    BASE + "/fr/7-parfums-pour-homme",
    BASE + "/fr/30-fragrances-pour-femme",
    BASE + "/fr/865-parfums-arabes-pour-hommes",
    BASE + "/fr/864-parfums-arabes-pour-femmes",
    BASE + "/fr/890-parfumerie-de-niche",
    BASE + "/fr/688-parfums-de-niche-pour-femme",
    BASE + "/fr/891-perfumes-nicho-unisex",
)

MAX_LINKS_PER_PAGE = 500
MAX_SECOND_HOP_PAGES = 40
MAX_THIRD_HOP_PAGES = 80


def _norm(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip().lower()


def _tokens(query):
    return [x for x in re.split(r"[^a-z0-9]+", _norm(query)) if len(x) > 1]


def _score(query, text):
    tokens = _tokens(query)
    hay = _norm(text)
    if not tokens:
        return 0.0
    return sum(token in hay for token in tokens) / len(tokens)


def _clean_url(url):
    parts = urlsplit(url)
    return urlunsplit(
        (
            parts.scheme.lower(),
            parts.netloc.lower(),
            parts.path,
            "",
            "",
        )
    )


def _is_internal(url):
    try:
        return urlsplit(url).netloc.lower() in {"www.sabina.com", "sabina.com"}
    except Exception:
        return False


def _is_product(url):
    u = (url or "").lower()
    if not _is_internal(u):
        return False
    if ".html" not in u:
        return False
    return not any(
        blocked in u
        for blocked in (
            "/ricerca",
            "/search",
            "/login",
            "/cart",
            "/account",
            "/suivi",
            "/seguimiento",
        )
    )


def _is_catalog(url):
    if not _is_internal(url) or _is_product(url):
        return False
    path = urlsplit(url).path.lower()
    return path.startswith("/fr/") and path != "/fr/"


def _fetch(session, url):
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        content_type = (response.headers.get("content-type") or "").lower()

        print(
            f"SABINA_TEST3: FETCH status={response.status_code} "
            f"url={url} final={response.url} bytes={len(response.content)} "
            f"type={content_type!r}"
        )

        if response.status_code != 200 or "text/html" not in content_type:
            response.close()
            return None, None

        return response.url, response.text

    except Exception as exc:
        print(
            f"SABINA_TEST3: FETCH_ERROR url={url} "
            f"error={type(exc).__name__}: {exc}"
        )
        return None, None


def _extract_links(html, base):
    soup = BeautifulSoup(html, "html.parser")

    links = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if not href:
            continue

        url = _clean_url(urljoin(base, href))

        if not _is_internal(url):
            continue

        if url in seen:
            continue

        seen.add(url)

        text = " ".join(anchor.stripped_strings)
        links.append((url, text))

        if len(links) >= MAX_LINKS_PER_PAGE:
            break

    return links


def _classify_links(links, query):
    products = []
    catalogs = []
    query_links = []

    for url, text in links:
        combined = f"{url} {text}"
        score = _score(query, combined)

        if _is_product(url):
            if score > 0:
                products.append((url, text, score))
            continue

        if _is_catalog(url):
            catalogs.append((url, text, score))
            if score > 0:
                query_links.append((url, text, score))

    return products, catalogs, query_links


def search(query):
    query = " ".join(str(query or "").split())

    if not query:
        return []

    print(f"SABINA_TEST3: START query={query!r}")
    print(f"SABINA_TEST3: TOKENS={_tokens(query)!r}")
    print("SABINA_TEST3: PURPOSE=SITE_GRAPH_DIAGNOSIS")

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        visited = set()
        catalog_pages = {}
        product_hits = {}

        # HOP 1: generic public catalog roots.
        # Record ALL catalog links, not only links containing query text.
        for root in ROOTS:
            final_url, html = _fetch(session, root)

            if not html:
                continue

            links = _extract_links(html, final_url)
            products, catalogs, query_links = _classify_links(links, query)

            print(
                f"SABINA_TEST3: ROOT_RESULT root={root} "
                f"links={len(links)} catalogs={len(catalogs)} "
                f"query_catalogs={len(query_links)} products={len(products)}"
            )

            for url, text, score in products:
                product_hits[url] = max(product_hits.get(url, 0.0), score)
                print(
                    f"SABINA_TEST3: ROOT_PRODUCT_MATCH score={score:.3f} "
                    f"url={url} text={text[:180]!r}"
                )

            for url, text, score in catalogs:
                catalog_pages.setdefault(
                    url,
                    {
                        "score": score,
                        "text": text,
                        "source": root,
                    },
                )

            for url, text, score in query_links:
                print(
                    f"SABINA_TEST3: ROOT_QUERY_CATALOG score={score:.3f} "
                    f"url={url} text={text[:180]!r}"
                )

        print(
            f"SABINA_TEST3: HOP1_CATALOGS={len(catalog_pages)} "
            f"HOP1_PRODUCTS={len(product_hits)}"
        )

        # HOP 2: inspect generic catalog/brand/category pages.
        # No query-token requirement on the intermediate page.
        hop2 = list(catalog_pages.items())[:MAX_SECOND_HOP_PAGES]

        for index, (url, meta) in enumerate(hop2, 1):
            if url in visited:
                continue

            visited.add(url)

            final_url, html = _fetch(session, url)

            if not html:
                continue

            links = _extract_links(html, final_url)
            products, catalogs, query_links = _classify_links(links, query)

            print(
                f"SABINA_TEST3: HOP2_RESULT {index}/{len(hop2)} "
                f"url={url} links={len(links)} catalogs={len(catalogs)} "
                f"query_catalogs={len(query_links)} products={len(products)}"
            )

            for product_url, text, score in products:
                product_hits[product_url] = max(
                    product_hits.get(product_url, 0.0),
                    score,
                )
                print(
                    f"SABINA_TEST3: HOP2_PRODUCT_MATCH score={score:.3f} "
                    f"url={product_url} text={text[:180]!r}"
                )

            for child_url, text, score in catalogs:
                if child_url not in catalog_pages:
                    catalog_pages[child_url] = {
                        "score": score,
                        "text": text,
                        "source": url,
                    }

                if score > 0:
                    print(
                        f"SABINA_TEST3: HOP2_QUERY_CATALOG score={score:.3f} "
                        f"url={child_url} text={text[:180]!r}"
                    )

        print(
            f"SABINA_TEST3: AFTER_HOP2 catalogs={len(catalog_pages)} "
            f"products={len(product_hits)}"
        )

        # HOP 3: inspect newly discovered catalog pages.
        remaining = [
            (url, meta)
            for url, meta in catalog_pages.items()
            if url not in visited
        ][:MAX_THIRD_HOP_PAGES]

        for index, (url, meta) in enumerate(remaining, 1):
            visited.add(url)

            final_url, html = _fetch(session, url)

            if not html:
                continue

            links = _extract_links(html, final_url)
            products, catalogs, query_links = _classify_links(links, query)

            print(
                f"SABINA_TEST3: HOP3_RESULT {index}/{len(remaining)} "
                f"url={url} links={len(links)} "
                f"query_catalogs={len(query_links)} products={len(products)}"
            )

            for product_url, text, score in products:
                product_hits[product_url] = max(
                    product_hits.get(product_url, 0.0),
                    score,
                )
                print(
                    f"SABINA_TEST3: HOP3_PRODUCT_MATCH score={score:.3f} "
                    f"url={product_url} text={text[:180]!r}"
                )

        print(f"SABINA_TEST3: FINAL_PRODUCTS={len(product_hits)}")
        print(f"SABINA_TEST3: FINAL_CATALOG_PAGES={len(catalog_pages)}")
        print(f"SABINA_TEST3: VISITED_CATALOG_PAGES={len(visited)}")

        if product_hits:
            print(
                "SABINA_TEST3: DIAGNOSIS="
                "PRODUCT_DISCOVERABLE_THROUGH_GENERIC_SITE_GRAPH"
            )
        elif len(catalog_pages) > len(ROOTS):
            print(
                "SABINA_TEST3: DIAGNOSIS="
                "SITE_GRAPH_REACHABLE_BUT_PRODUCT_LINK_NOT_EXPOSED_IN_TEST_DEPTH"
            )
        else:
            print(
                "SABINA_TEST3: DIAGNOSIS="
                "GENERIC_ROOTS_DO_NOT_EXPOSE_ENOUGH_CATALOG_GRAPH"
            )

        # Diagnostic only: never fabricate results.
        return []

    finally:
        session.close()


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    search(" ".join(sys.argv[1:]).strip() or "Liquid brun")
