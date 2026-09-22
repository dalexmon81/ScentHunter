from fastapi import APIRouter, Query
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

router = APIRouter()

UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
    "Mobile/15E148 Safari/604.1"
)

HEADERS = {
    "User-Agent": UA,
    "Accept-Language": "en-GB,en;q=0.9",
}
TIMEOUT = (1.5, 4.0)

MAX_DELOOX_PAGES = 8
MAX_SABINA_URLS = 12


def _norm(value):
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _tokens(value):
    stop = {"ml", "eau", "de", "parfum", "perfume", "fragrance"}
    return [x for x in _norm(value).split() if len(x) > 1 and x not in stop]


def _get(session, url):
    started = time.perf_counter()

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        return {
            "ok": 200 <= response.status_code < 400,
            "status": response.status_code,
            "url": response.url,
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "bytes": len(response.content),
            "text": response.text,
            "error": None,
        }
    except requests.RequestException as exc:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.perf_counter() - started, 3),
            "bytes": 0,
            "text": "",
            "error": f"{type(exc).__name__}: {exc}",
        }


def _links(html, base, fragment):
    soup = BeautifulSoup(html or "", "html.parser")
    found = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = urljoin(base, anchor.get("href", "")).split("#")[0]

        if fragment and fragment not in urlparse(url).path.lower():
            continue

        if url not in seen:
            seen.add(url)
            found.append(url)

    return found


def _title(html):
    soup = BeautifulSoup(html or "", "html.parser")

    h1 = soup.find("h1")
    if h1:
        return re.sub(r"\s+", " ", h1.get_text(" ", strip=True))

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text(strip=True))
        except Exception:
            continue

        items = data if isinstance(data, list) else [data]

        for item in items:
            if isinstance(item, dict) and item.get("name"):
                return str(item["name"]).strip()

    return ""


@router.get("/diagnose-sabina-catalog")
def diagnose_sabina_catalog(q: str = Query("Liquid Brun")):
    started = time.perf_counter()
    session = requests.Session()
    session.headers.update(HEADERS)

    tokens = _tokens(q)

    probes = [
        "/it/sitemap.xml",
        "/sitemap.xml",
        "/it/sitemap_index.xml",
        "/sitemap_index.xml",
        "/it/sitemap-products.xml",
        "/it/sitemap_products.xml",
    ]

    results = []
    catalog_urls = []

    for path in probes:
        response = _get(session, "https://www.sabina.com" + path)

        results.append(
            {
                key: value
                for key, value in response.items()
                if key != "text"
            }
        )

        if response["ok"] and response["text"]:
            for match in re.finditer(
                r'https?://(?:www\.)?sabina\.com/[^"<>\\s]+',
                response["text"],
                re.I,
            ):
                url = match.group(0).replace("&amp;", "&")

                if "/it/" in url and url not in catalog_urls:
                    catalog_urls.append(url)

    search_url = (
        "https://www.sabina.com/it/ricerca_old?s="
        + requests.utils.quote(q)
    )

    search_response = _get(session, search_url)

    results.append(
        {
            key: value
            for key, value in search_response.items()
            if key != "text"
        }
    )

    if search_response["ok"]:
        catalog_urls.extend(
            _links(
                search_response["text"],
                "https://www.sabina.com",
                "",
            )
        )

    catalog_urls = list(dict.fromkeys(catalog_urls))

    token_hit_urls = [
        url
        for url in catalog_urls
        if any(token in _norm(url) for token in tokens)
    ]

    verification = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_get, session, url): url
            for url in token_hit_urls[:MAX_SABINA_URLS]
        }

        for future in as_completed(futures):
            url = futures[future]
            response = future.result()

            title = _title(response.get("text", "")) if response["ok"] else ""

            verification.append(
                {
                    "url": url,
                    "http_status": response["status"],
                    "title": title,
                    "query_token_match": (
                        all(token in _norm(title) for token in tokens)
                        if title
                        else False
                    ),
                    "elapsed_sec": response["elapsed_sec"],
                    "error": response["error"],
                }
            )

    session.close()

    return {
        "diagnostic": True,
        "store": "Sabina",
        "query": q,
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "summary": {
            "sitemap_probes": len(probes),
            "catalog_urls": len(catalog_urls),
            "token_hit_urls": len(token_hit_urls),
            "verified_product_hits": sum(
                1
                for item in verification
                if item["query_token_match"]
            ),
        },
        "probes": results,
        "token_hit_urls": token_hit_urls[:MAX_SABINA_URLS],
        "verification": verification,
    }


@router.get("/diagnose-deloox-catalog")
def diagnose_deloox_catalog(q: str = Query("Liquid Brun")):
    started = time.perf_counter()
    session = requests.Session()
    session.headers.update(HEADERS)

    tokens = _tokens(q)
    base = "https://www.deloox.com"

    seeds = [
        base + "/category/1000054/mens-fragrances.html",
        base + "/category/1075639/womens-fragrances.html",
        base + "/category/1075750/mens-perfume.html",
        base + "/category/1079036/armaf-fragrances.html",
    ]

    pages = []
    seen_pages = set()

    def add_page(url):
        if url in seen_pages:
            return

        if len(seen_pages) >= MAX_DELOOX_PAGES:
            return

        seen_pages.add(url)
        pages.append(url)

    for seed in seeds:
        add_page(seed)

    index = 0

    while index < len(pages):
        url = pages[index]
        index += 1

        response = _get(session, url)

        item = {
            "url": url,
            "status": response["status"],
            "elapsed_sec": response["elapsed_sec"],
            "bytes": response["bytes"],
            "error": response["error"],
        }

        if response["ok"]:
            links = _links(
                response["text"],
                base,
                "/product/",
            )

            item["product_link_count"] = len(links)

            item["token_hit_links"] = [
                link
                for link in links
                if any(token in _norm(link) for token in tokens)
            ][:20]

            soup = BeautifulSoup(
                response["text"],
                "html.parser",
            )

            for anchor in soup.find_all("a", href=True):
                text = re.sub(
                    r"\s+",
                    " ",
                    anchor.get_text(" ", strip=True),
                ).lower()

                href = urljoin(
                    url,
                    anchor["href"],
                ).split("#")[0]

                is_next = (
                    "next" in text
                    or "page=" in href.lower()
                    or "/page/" in href.lower()
                )

                if is_next and "/category/" in href:
                    add_page(href)

        pages[index - 1] = item

    candidates = []

    for page in pages:
        if "url" not in page:
            continue

        response = _get(session, page["url"])

        if response["ok"]:
            candidates.extend(
                _links(
                    response["text"],
                    base,
                    "/product/",
                )
            )

    candidates = list(dict.fromkeys(candidates))

    token_hits = [
        url
        for url in candidates
        if any(token in _norm(url) for token in tokens)
    ]

    verification = []

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_get, session, url): url
            for url in token_hits[:20]
        }

        for future in as_completed(futures):
            url = futures[future]
            response = future.result()

            title = _title(response.get("text", "")) if response["ok"] else ""

            verification.append(
                {
                    "url": url,
                    "http_status": response["status"],
                    "title": title,
                    "query_token_match": (
                        all(token in _norm(title) for token in tokens)
                        if title
                        else False
                    ),
                    "elapsed_sec": response["elapsed_sec"],
                    "error": response["error"],
                }
            )

    session.close()

    return {
        "diagnostic": True,
        "store": "Deloox",
        "query": q,
        "elapsed_sec": round(time.perf_counter() - started, 3),
        "summary": {
            "category_pages_tested": len(pages),
            "product_urls_seen": len(candidates),
            "token_hit_urls": len(token_hits),
            "verified_product_hits": sum(
                1
                for item in verification
                if item["query_token_match"]
            ),
        },
        "pages": pages,
        "token_hit_urls": token_hits[:20],
        "verification": verification,
    }
