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
            f"SABINA_TEST4: FETCH status={response.status_code} "
            f"url={url} final={response.url} bytes={len(response.content)} "
            f"type={content_type!r}"
        )

        if response.status_code != 200 or "text/html" not in content_type:
            response.close()
            return None, None

        return response.url, response.text

    except Exception as exc:
        print(
            f"SABINA_TEST4: FETCH_ERROR url={url} "
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


def _pagination_urls(links, current_url):
    out = []
    seen = set()
    current = urlsplit(current_url)

    for url, text in links:
        if url in seen:
            continue

        parts = urlsplit(url)
        qs = parts.query.lower()
        low_text = _norm(text)

        is_page_param = bool(
            re.search(r"(?:^|[?&])p=\d+(?:&|$)", qs)
            or re.search(r"(?:^|[?&])page=\d+(?:&|$)", qs)
        )

        is_next = any(
            marker in low_text
            for marker in ("suivant", "next", "siguiente", "›", "»")
        )

        same_path = (
            parts.netloc.lower() == current.netloc.lower()
            and parts.path.lower() == current.path.lower()
        )

        if same_path and (is_page_param or is_next):
            seen.add(url)
            out.append(url)

    return out


def _page_number(url):
    query = urlsplit(url).query
    for key in ("p", "page"):
        m = re.search(
            r"(?:^|&)"+re.escape(key)+r"=(\d+)(?:&|$)",
            query,
            re.I,
        )
        if m:
            return int(m.group(1))
    return None


def _discover_page(session, url, query, source):
    final_url, html = _fetch(session, url)

    if not html:
        return [], []

    links = _extract_links(html, final_url)
    products, catalogs, query_links = _classify_links(links, query)
    pages = _pagination_urls(links, final_url)

    print(
        f"SABINA_TEST4: PAGE source={source} "
        f"url={url} links={len(links)} products={len(products)} "
        f"pagination={len(pages)}"
    )

    return products, pages


def _verify_product(session, query, url):
    final_url, html = _fetch(session, url)

    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    title = " ".join(h1.stripped_strings) if h1 else ""

    if not title and soup.title:
        title = " ".join(soup.title.stripped_strings)

    score = _score(query, title)

    # ALL query tokens must be present.
    if score < 1.0:
        print(
            f"SABINA_TEST4: REJECT_PARTIAL score={score:.3f} "
            f"title={title!r} url={final_url}"
        )
        return None

    print(
        f"SABINA_TEST4: EXACT_PRODUCT score={score:.3f} "
        f"title={title!r} url={final_url}"
    )

    return {
        "name": title,
        "url": final_url,
        "price": None,
    }


def search(query):
    query = " ".join(str(query or "").split())

    if not query:
        return []

    print(f"SABINA_TEST4: START query={query!r}")
    print(f"SABINA_TEST4: TOKENS={_tokens(query)!r}")
    print("SABINA_TEST4: PURPOSE=PAGINATION_AWARE_GENERIC_DISCOVERY")

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # Generic perfume/catalog entry points only.
        roots = (
            BASE + "/fr/7-parfums-pour-homme",
            BASE + "/fr/31-fragrances-pour-homme",
            BASE + "/fr/6-parfums-pour-femme",
            BASE + "/fr/30-fragrances-pour-femme",
            BASE + "/fr/864-parfums-arabes-pour-femmes",
            BASE + "/fr/865-parfums-arabes-pour-hommes",
            BASE + "/fr/890-parfumerie-de-niche",
            BASE + "/fr/688-parfums-de-niche-pour-femme",
            BASE + "/fr/891-perfumes-nicho-unisex",
        )

        candidate_products = {}
        pagination_queue = []
        visited_pages = set()

        # First pass: roots.
        for root in roots:
            products, pages = _discover_page(
                session,
                root,
                query,
                "ROOT",
            )

            for url, text, score in products:
                candidate_products[url] = max(
                    candidate_products.get(url, 0.0),
                    score,
                )

            pagination_queue.extend(pages)

        print(
            f"SABINA_TEST4: ROOTS_DONE "
            f"pagination_queue={len(pagination_queue)} "
            f"candidates={len(candidate_products)}"
        )

        # Follow pagination generically. No assumed page number.
        MAX_PAGINATION_PAGES = 2500

        while pagination_queue and len(visited_pages) < MAX_PAGINATION_PAGES:
            page_url = pagination_queue.pop(0)

            if page_url in visited_pages:
                continue

            visited_pages.add(page_url)

            products, pages = _discover_page(
                session,
                page_url,
                query,
                f"PAGINATION_{_page_number(page_url) or '?'}",
            )

            for url, text, score in products:
                candidate_products[url] = max(
                    candidate_products.get(url, 0.0),
                    score,
                )

            for next_page in pages:
                if next_page not in visited_pages:
                    pagination_queue.append(next_page)

            if len(visited_pages) % 25 == 0:
                print(
                    f"SABINA_TEST4: PAGINATION_PROGRESS "
                    f"visited={len(visited_pages)} "
                    f"queue={len(pagination_queue)} "
                    f"candidates={len(candidate_products)}"
                )

        print(
            f"SABINA_TEST4: DISCOVERY_DONE "
            f"pagination_visited={len(visited_pages)} "
            f"pagination_queue={len(pagination_queue)} "
            f"candidate_products={len(candidate_products)}"
        )

        # Verify only candidates and require ALL query tokens.
        results = []

        for url, discovery_score in sorted(
            candidate_products.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            result = _verify_product(session, query, url)
            if result:
                results.append(result)

        print(f"SABINA_TEST4: FINAL_EXACT_PRODUCTS={len(results)}")

        for result in results:
            print(
                f"SABINA_TEST4: RESULT "
                f"name={result['name']!r} url={result['url']}"
            )

        if results:
            print(
                "SABINA_TEST4: DIAGNOSIS="
                "PRODUCT_FOUND_VIA_GENERIC_PAGINATION"
            )
        else:
            print(
                "SABINA_TEST4: DIAGNOSIS="
                "NO_EXACT_PRODUCT_FOUND_IN_GENERIC_PAGINATION_GRAPH"
            )

        return []

    finally:
        session.close()

def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    search(" ".join(sys.argv[1:]).strip() or "")
