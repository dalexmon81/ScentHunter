import re
import sys
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE = "https://www.sabina.com"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}


def log(*parts):
    print("SABINA_TEST7", *parts, flush=True)


def request(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        ct = r.headers.get("content-type", "")
        log(
            "REQUEST",
            url,
            "status=", r.status_code,
            "final=", r.url,
            "type=", ct,
            "bytes=", len(r.content),
        )
        return r
    except Exception as e:
        log("REQUEST_ERROR", url, type(e).__name__, str(e))
        return None


def xml_urls(text):
    out = []
    try:
        soup = BeautifulSoup(text, "xml")
        for tag in soup.find_all(["loc", "url", "sitemap"]):
            value = tag.get_text(" ", strip=True)
            if value.startswith("http"):
                out.append(value)
    except Exception:
        pass

    if not out:
        for value in re.findall(r"https?://[^<\s]+", text):
            value = value.rstrip(" \t\r\n\"'")
            if value not in out:
                out.append(value)

    return list(dict.fromkeys(out))


def looks_product(url):
    p = urlparse(url).path.lower()
    bad = (
        "/category/",
        "/categories/",
        "/blog",
        "/content/",
        "/marca/",
        "/brand/",
        "/module/",
        "/modules/",
        "/search",
        "/ricerca",
        "/buscar",
        "/suchen",
        "/recherche",
    )
    if any(x in p for x in bad):
        return False

    # Sabina/PrestaShop product URLs normally contain a numeric product id
    # followed by a rewritten slug. This is deliberately generic.
    return bool(re.search(r"/(?:[a-z]{2}/)?\d+-[^/?#]+$", p))


def candidate_endpoint_paths():
    # These are discovery probes for the generic Advanced Search sitemap
    # mechanism exposed by robots.txt. No product names or product URLs.
    return [
        "/modules/pm_advancedsearch4/sitemap/",
        "/modules/pm_advancedsearch4/sitemap",
        "/modules/pm_advancedsearch4/sitemap/index.xml",
        "/modules/pm_advancedsearch4/sitemap/sitemap.xml",
        "/modules/pm_advancedsearch4/sitemap/index",
        "/modules/pm_advancedsearch4/sitemap/products.xml",
        "/modules/pm_advancedsearch4/sitemap/product.xml",
        "/modules/pm_advancedsearch4/sitemap/1.xml",
        "/modules/pm_advancedsearch4/sitemap/1",
        "/modules/pm_advancedsearch4/sitemap/products/1",
        "/modules/pm_advancedsearch4/sitemap/product/1",
    ]


def main():
    query = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""
    if not query:
        query = "Liquid brun"

    log("query:", repr(query))
    log("phase:", "robots_and_sitemap")

    robots = request(BASE + "/robots.txt")
    sitemap_urls = []

    if robots is not None and robots.ok:
        for line in robots.text.splitlines():
            if line.lower().startswith("sitemap:"):
                u = line.split(":", 1)[1].strip()
                if u:
                    sitemap_urls.append(u)
                    log("ROBOTS_SITEMAP:", u)

        for line in robots.text.splitlines():
            if "pm_advancedsearch4/sitemap" in line.lower():
                log("ROBOTS_ADVANCEDSEARCH_ALLOW:", line.strip())

    sitemap_urls = list(dict.fromkeys(sitemap_urls))

    # Read the shop sitemap if available.
    for u in sitemap_urls:
        r = request(u)
        if r is None or not r.ok:
            continue

        urls = xml_urls(r.text)
        log("SITEMAP_URL_COUNT:", u, len(urls))

        # If it is an index, inspect its children.
        children = [
            x for x in urls
            if "sitemap" in x.lower() and x.rstrip("/") != u.rstrip("/")
        ]

        for child in children[:100]:
            cr = request(child)
            if cr is None or not cr.ok:
                continue
            cu = xml_urls(cr.text)
            product_candidates = [x for x in cu if looks_product(x)]
            log(
                "SITEMAP_CHILD:",
                child,
                "urls=", len(cu),
                "product_candidates=", len(product_candidates),
            )

    log("phase:", "advancedsearch4_endpoint_probes")

    successful = []
    for path in candidate_endpoint_paths():
        u = urljoin(BASE, path)
        r = request(u)
        if r is None:
            continue

        ct = r.headers.get("content-type", "").lower()
        body = r.text[:200000]

        if r.status_code == 200:
            urls = xml_urls(body)
            products = [x for x in urls if looks_product(x)]

            log(
                "ENDPOINT_RESULT:",
                u,
                "urls=", len(urls),
                "product_candidates=", len(products),
                "xml_like=", ("xml" in ct or body.lstrip().startswith("<?xml")),
            )

            if urls or "xml" in ct or body.lstrip().startswith("<?xml"):
                successful.append((u, len(urls), len(products)))

    log("successful_endpoint_probes:", len(successful))
    for u, n, p in successful:
        log("SUCCESS:", u, "urls=", n, "product_candidates=", p)

    log("phase:", "search_page_control")
    search_urls = [
        f"{BASE}/it/ricerca_old?s={requests.utils.quote(query)}",
        f"{BASE}/it/ricerca_old?search_query={requests.utils.quote(query)}",
        f"{BASE}/it/ricerca?search_query={requests.utils.quote(query)}",
    ]

    for u in search_urls:
        r = request(u)
        if r is None or not r.ok:
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        hrefs = []
        for a in soup.find_all("a", href=True):
            h = urljoin(r.url, a.get("href", "").strip())
            if h.startswith(BASE) and h not in hrefs:
                hrefs.append(h)

        product_hrefs = [h for h in hrefs if looks_product(h)]

        log(
            "SEARCH_PAGE:",
            u,
            "links=", len(hrefs),
            "generic_product_urls=", len(product_hrefs),
        )

        # Only print URLs that actually look like product URLs.
        for h in product_hrefs[:30]:
            label = soup.find("a", href=lambda x: x and urljoin(r.url, x.strip()) == h)
            text = label.get_text(" ", strip=True) if label else ""
            log("SEARCH_PRODUCT_CANDIDATE:", h, "label=", repr(text[:180]))

    log("FINAL: test_complete")


if __name__ == "__main__":
    main()
