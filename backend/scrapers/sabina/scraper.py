import re
import json
import unicodedata
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
        "Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": BASE + "/fr/",
}

# Generic perfume/catalog entry points only.
ROOTS = (
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


def _norm(value):
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(c for c in value if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", value).strip().lower()


def _tokens(query):
    return [x for x in re.split(r"[^a-z0-9]+", _norm(query)) if len(x) > 1]


def _score(query, text):
    ts = _tokens(query)
    hay = _norm(text)
    return sum(t in hay for t in ts) / len(ts) if ts else 0.0


def _clean_url(url):
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path, p.query, ""))


def _internal(url):
    try:
        return urlsplit(url).netloc.lower() in {"sabina.com", "www.sabina.com"}
    except Exception:
        return False


def _product_like(url):
    if not _internal(url):
        return False
    path = urlsplit(url).path.lower()
    if not path.startswith("/fr/"):
        return False
    if any(x in path for x in (
        "/content/", "/search", "/recherche", "/login",
        "/mon-compte", "/panier", "/cart", "/contact",
        "/faq", "/magasins"
    )):
        return False

    # Sabina product URLs observed in the diagnostic have a numeric
    # product id in the path and normally end in .html. Do not require
    # one particular category or product name.
    return bool(re.search(r"/\d+[-/]", path)) or path.endswith(".html")


def _fetch(session, url):
    try:
        r = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        ct = (r.headers.get("content-type") or "").lower()
        print(
            f"SABINA_FINAL: FETCH status={r.status_code} "
            f"url={url} final={r.url} bytes={len(r.content)} type={ct!r}"
        )
        if r.status_code != 200 or "text/html" not in ct:
            return None, None
        return r.url, r.text
    except Exception as exc:
        print(
            f"SABINA_FINAL: FETCH_ERROR url={url} "
            f"error={type(exc).__name__}: {exc}"
        )
        return None, None


def _pagination_links(soup, base):
    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        u = _clean_url(urljoin(base, a["href"]))
        if not _internal(u) or u in seen:
            continue

        q = urlsplit(u).query.lower()
        text = _norm(" ".join(a.stripped_strings))

        is_page = bool(
            re.search(r"(?:^|&)p=\d+(?:&|$)", q)
            or re.search(r"(?:^|&)page=\d+(?:&|$)", q)
        )
        is_nav = any(
            marker in text
            for marker in ("suivant", "next", "siguiente",
                           "précédent", "precedent")
        )

        if is_page or is_nav:
            seen.add(u)
            out.append(u)

    return out


def _diagnose_page(html, base, query):
    """
    Definitive structural test.

    It does NOT stop at 180 links.
    It checks:
      1. normal <a href>
      2. product-card/container attributes
      3. JSON-LD Product objects
      4. raw HTML product-like URLs
      5. pagination links

    This tells us exactly where Sabina exposes (or hides) products.
    """
    soup = BeautifulSoup(html, "html.parser")
    raw = _norm(html)
    ts = _tokens(query)

    anchors = soup.find_all("a", href=True)
    products = []
    exact = []
    seen_products = set()

    for a in anchors:
        u = _clean_url(urljoin(base, a["href"]))
        text = " ".join(a.stripped_strings)
        sc = _score(query, f"{u} {text}")

        if _internal(u) and _product_like(u) and u not in seen_products:
            seen_products.add(u)
            products.append((u, text, sc))

        if _internal(u) and sc == 1.0:
            exact.append((u, text))

    pages = _pagination_links(soup, base)

    print(f"SABINA_FINAL: TOKENS={ts!r}")
    print(f"SABINA_FINAL: QUERY_TEXT_IN_HTML={all(t in raw for t in ts)}")
    print(
        f"SABINA_FINAL: ANCHORS={len(anchors)} "
        f"PRODUCT_LIKE_ANCHORS={len(products)} "
        f"EXACT_QUERY_ANCHORS={len(exact)} "
        f"PAGINATION={len(pages)}"
    )

    for u, text, sc in products[:40]:
        print(
            f"SABINA_FINAL: PRODUCT_LIKE score={sc:.3f} "
            f"url={u} text={text!r}"
        )

    # Product-card evidence, including data-* URLs.
    containers = []
    marker = re.compile(
        r"product|produit|item|article|catalog|js-product",
        re.I,
    )

    for node in soup.find_all(["article", "li", "div"]):
        attrs = " ".join(
            str(node.get(k, ""))
            for k in (
                "id", "class", "data-product-id", "data-id",
                "data-product-url", "data-url", "data-href"
            )
        )

        if not marker.search(attrs):
            continue

        urls = []

        for a in node.find_all("a", href=True):
            u = _clean_url(urljoin(base, a["href"]))
            if _internal(u):
                urls.append(u)

        for attr in ("data-product-url", "data-url", "data-href"):
            value = node.get(attr)
            if value:
                urls.append(_clean_url(urljoin(base, str(value))))

        urls = list(dict.fromkeys(urls))

        if urls:
            containers.append((
                urls,
                " ".join(node.stripped_strings)[:300],
                attrs[:300],
            ))

    print(f"SABINA_FINAL: PRODUCT_MARKER_CONTAINERS={len(containers)}")

    for urls, text, attrs in containers[:30]:
        print(
            f"SABINA_FINAL: CONTAINER urls={urls[:6]} "
            f"text={text!r} attrs={attrs!r}"
        )

    # JSON-LD Product evidence.
    json_products = []

    for script in soup.find_all(
        "script",
        type=lambda x: x and "ld+json" in x,
    ):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            obj = stack.pop()

            if isinstance(obj, list):
                stack.extend(obj)
                continue

            if not isinstance(obj, dict):
                continue

            typ = obj.get("@type")
            if typ == "Product" or (
                isinstance(typ, list) and "Product" in typ
            ):
                json_products.append(obj)

            for value in obj.values():
                if isinstance(value, (dict, list)):
                    stack.append(value)

    print(f"SABINA_FINAL: JSONLD_PRODUCTS={len(json_products)}")

    for obj in json_products[:30]:
        print(
            f"SABINA_FINAL: JSONLD name={obj.get('name')!r} "
            f"url={obj.get('url')!r} sku={obj.get('sku')!r}"
        )

    # Raw HTML URL evidence.
    raw_product_urls = []

    for match in re.findall(
        r"https?://[^\"'<>\\s]+",
        html,
    ):
        u = _clean_url(match.rstrip(".,);"))

        if _product_like(u) and u not in raw_product_urls:
            raw_product_urls.append(u)

    print(
        f"SABINA_FINAL: RAW_PRODUCT_LIKE_URLS="
        f"{len(raw_product_urls)}"
    )

    for u in raw_product_urls[:40]:
        print(f"SABINA_FINAL: RAW_PRODUCT_URL {u}")

    return products, pages, json_products, containers


def _verify(session, query, urls):
    results = []

    for url in urls[:50]:
        final, html = _fetch(session, url)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        h1 = soup.find("h1")

        if h1:
            title = " ".join(h1.stripped_strings)
        elif soup.title:
            title = soup.title.get_text(" ", strip=True)
        else:
            title = ""

        sc = _score(query, title)

        print(
            f"SABINA_FINAL: VERIFY score={sc:.3f} "
            f"title={title!r} url={final}"
        )

        if sc == 1.0:
            results.append({
                "name": title,
                "url": final,
                "price": None,
            })

    return results


def search(query):
    query = " ".join(str(query or "").split())

    if not query:
        return []

    print(f"SABINA_FINAL: START query={query!r}")
    print("SABINA_FINAL: PURPOSE=DEFINITIVE_STRUCTURE_TEST")

    session = requests.Session()
    session.headers.update(HEADERS)

    queue = list(ROOTS)
    visited = set()
    candidate_urls = []

    try:
        # We deliberately inspect roots first and then follow the site's
        # own pagination graph. No product, brand or perfume URL is seeded.
        while queue and len(visited) < 120:
            url = queue.pop(0)

            if url in visited:
                continue

            visited.add(url)

            final, html = _fetch(session, url)
            if not html:
                continue

            products, pages, json_products, containers = _diagnose_page(
                html,
                final,
                query,
            )

            for product_url, text, sc in products:
                if sc > 0 and product_url not in candidate_urls:
                    candidate_urls.append(product_url)

            for obj in json_products:
                product_url = obj.get("url")
                name = obj.get("name", "")

                if isinstance(product_url, str):
                    product_url = _clean_url(
                        urljoin(final, product_url)
                    )

                    if (
                        _product_like(product_url)
                        and _score(
                            query,
                            product_url + " " + str(name),
                        ) > 0
                        and product_url not in candidate_urls
                    ):
                        candidate_urls.append(product_url)

            for urls, text, attrs in containers:
                for product_url in urls:
                    if (
                        _product_like(product_url)
                        and _score(
                            query,
                            product_url + " " + text,
                        ) > 0
                        and product_url not in candidate_urls
                    ):
                        candidate_urls.append(product_url)

            for page in pages:
                if page not in visited and page not in queue:
                    queue.append(page)

            print(
                f"SABINA_FINAL: PAGE_DONE visited={len(visited)} "
                f"queue={len(queue)} candidates={len(candidate_urls)}"
            )

            # If a generic path has produced a query-matching URL,
            # verification is enough to classify the architecture.
            if candidate_urls:
                break

        print(
            f"SABINA_FINAL: GRAPH_DONE visited={len(visited)} "
            f"queue={len(queue)} candidates={len(candidate_urls)}"
        )

        results = _verify(session, query, candidate_urls)

        print(
            f"SABINA_FINAL: VERIFIED_RESULTS={len(results)}"
        )

        if results:
            print(
                "SABINA_FINAL: DIAGNOSIS="
                "GENERIC_DISCOVERY_AND_VERIFICATION_WORKS"
            )
        elif candidate_urls:
            print(
                "SABINA_FINAL: DIAGNOSIS="
                "PRODUCT_URLS_FOUND_BUT_VERIFICATION_REJECTS_QUERY"
            )
        else:
            print(
                "SABINA_FINAL: DIAGNOSIS="
                "NO_QUERY_MATCHING_PRODUCT_PATH_IN_STATIC_STRUCTURE"
            )

        # Diagnostic only: production result contract is untouched.
        return []

    finally:
        session.close()


def scrape(query):
    return search(query)


def search_sabina(query):
    return search(query)


if __name__ == "__main__":
    import sys
    search(" ".join(sys.argv[1:]).strip())
