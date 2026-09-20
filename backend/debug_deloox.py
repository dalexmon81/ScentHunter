"""
ScentHunter — Deloox Born-in-Roma diagnostic.

This is the COMPLETE debug_deloox.py file.

HTTP endpoint:
    GET /diagnose-deloox-born4

IMPORTANT:
- Read-only diagnostic.
- It does NOT call the production Deloox search() function.
- It does NOT parse the entire Born in Roma catalogue.
- It only tests the discovery surfaces needed for the four missing variants.
- Requests are parallelized so the endpoint cannot sit for minutes waiting
  on sequential Deloox requests.
"""

from __future__ import annotations

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter

router = APIRouter()

BASE = "https://www.deloox.be"
TIMEOUT = (1.0, 2.5)
MAX_WORKERS = 8

TARGETS = [
    {
        "canonical": "Born in Roma Uomo The Gold",
        "aliases": [
            "Born in Roma Uomo The Gold",
            "Born In Roma The Gold Uomo",
            "Valentino Born In Roma The Gold Uomo",
            "The Gold Uomo",
        ],
        "categories": [
            f"{BASE}/categorie/1075744/eau-de-toilette-homme.html",
            f"{BASE}/categorie/1075744/eau-de-toilette-homme.html?page=2",
        ],
    },
    {
        "canonical": "Born in Roma Uomo Ivory",
        "aliases": [
            "Born in Roma Uomo Ivory",
            "Born In Roma Ivory Uomo",
            "Valentino Born In Roma Ivory Uomo",
            "Ivory Uomo",
        ],
        "categories": [
            f"{BASE}/categorie/1075744/eau-de-toilette-homme.html",
            f"{BASE}/categorie/1075744/eau-de-toilette-homme.html?page=2",
        ],
    },
    {
        "canonical": "Born in Roma Donna The Gold",
        "aliases": [
            "Born in Roma Donna The Gold",
            "Born In Roma The Gold Donna",
            "Valentino Born In Roma The Gold Donna",
            "The Gold Donna",
        ],
        "categories": [
            f"{BASE}/categorie/1075743/eau-de-parfum-femme.html",
            f"{BASE}/categorie/1075742/eau-de-parfum-femme.html",
        ],
    },
    {
        "canonical": "Born in Roma Donna Ivory",
        "aliases": [
            "Born in Roma Donna Ivory",
            "Donna Born in Roma Ivory",
            "Born In Roma Ivory Donna",
            "Valentino Donna Born In Roma Ivory",
            "Ivory Donna",
        ],
        "categories": [
            f"{BASE}/categorie/1075743/eau-de-parfum-femme.html",
            f"{BASE}/categorie/1075742/eau-de-parfum-femme.html",
        ],
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,"
              "application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}

PRODUCT_RE = re.compile(
    r"(?:https?:\\?/\\?/[^\"'<>\\s]+)?/"
    r"(?:produit|product|producto|prodotto)/"
    r"\d+/[^\"'<>\\s?#]+",
    re.I,
)

NON_PRODUCT = (
    "body mist",
    "body spray",
    "body lotion",
    "body cream",
    "deodorant",
    "after shave",
    "aftershave",
    "shower gel",
    "hair mist",
    "hair body mist",
    "hair and body mist",
    "body hair mist",
    "coffret",
    "cadeau",
    "gift set",
    "giftset",
    "set cadeau",
    "geschenkset",
)


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def tokens(value) -> set[str]:
    return {x for x in norm(value).split() if len(x) > 1}


def request(session: requests.Session, url: str) -> dict:
    started = time.time()

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        return {
            "ok": response.status_code == 200 and bool(response.text),
            "status": response.status_code,
            "url": response.url,
            "bytes": len(response.text or ""),
            "html": response.text or "",
            "elapsed": round(time.time() - started, 2),
            "error": None,
        }

    except requests.RequestException as exc:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "bytes": 0,
            "html": "",
            "elapsed": round(time.time() - started, 2),
            "error": f"{type(exc).__name__}: {exc}",
        }


def is_product_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    host = parsed.netloc.lower().split(":", 1)[0]

    if host not in {"deloox.be", "www.deloox.be"}:
        return False

    return bool(
        re.search(
            r"/(?:product|produit|producto|prodotto)/\d+/",
            parsed.path,
            re.I,
        )
    )


def normalize_product_url(raw: str) -> str:
    raw = clean(raw).replace("\\/", "/")

    if not raw:
        return ""

    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = urljoin(BASE + "/", raw)

    raw = raw.split("#", 1)[0].split("?", 1)[0]

    return raw if is_product_url(raw) else ""


def product_slug(url: str) -> str:
    try:
        return clean(urlparse(url).path.rsplit("/", 1)[-1])
    except Exception:
        return ""


def is_born_product(url: str) -> bool:
    value = norm(product_slug(url))

    if "born" not in value or "roma" not in value:
        return False

    return not any(norm(x) in value for x in NON_PRODUCT)


def extract_product_urls(html: str) -> list[str]:
    found = set()

    soup = BeautifulSoup(html or "", "html.parser")

    for anchor in soup.find_all("a", href=True):
        url = normalize_product_url(anchor.get("href"))
        if url and not any(
            norm(x) in norm(product_slug(url))
            for x in NON_PRODUCT
        ):
            found.add(url)

    for raw in PRODUCT_RE.findall(html or ""):
        url = normalize_product_url(raw)
        if url:
            found.add(url)

    return sorted(found)


def score_target(url: str, target: dict) -> tuple[float, str]:
    text = norm(product_slug(url))
    best = 0.0
    matched = ""

    for alias in target["aliases"]:
        wanted = tokens(alias)
        if not wanted:
            continue

        hits = sum(token in text for token in wanted)
        score = hits / len(wanted)

        if {"born", "roma"} <= wanted and {"born", "roma"} <= tokens(text):
            score += 0.15

        if score > best:
            best = score
            matched = alias

    return min(best, 1.0), matched


def target_candidates(urls: list[str], target: dict) -> list[dict]:
    result = []

    for url in urls:
        if not is_born_product(url):
            continue

        score, alias = score_target(url, target)
        slug = product_slug(url)

        words = tokens(slug)
        distinctive = {"gold", "ivory"} & words
        gender = {"uomo", "donna"} & words

        if score >= 0.60 or (
            {"born", "roma"} <= words
            and distinctive
            and gender
        ):
            result.append({
                "url": url,
                "slug": slug,
                "score": round(score, 3),
                "matched_alias": alias,
            })

    result.sort(key=lambda x: (-x["score"], x["url"]))
    return result


def parse_product_page(session: requests.Session, url: str, target: dict) -> dict:
    response = request(session, url)

    result = {
        "url": url,
        "reachable": response["ok"],
        "status": response["status"],
        "elapsed": response["elapsed"],
        "jsonld_names": [],
        "target_name_match": False,
        "offers": 0,
        "error": response["error"],
    }

    if not response["ok"]:
        return result

    soup = BeautifulSoup(response["html"], "html.parser")

    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.get_text())
        except Exception:
            continue

        stack = list(data) if isinstance(data, list) else [data]

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            typ = item.get("@type")

            if typ == "Product" or (
                isinstance(typ, list) and "Product" in typ
            ):
                name = clean(item.get("name"))

                if name:
                    result["jsonld_names"].append(name)

                    score, _ = score_target(
                        name.replace(" ", "-"),
                        target,
                    )

                    if score >= 0.60:
                        result["target_name_match"] = True

                offers = item.get("offers")

                if isinstance(offers, dict):
                    offers = [offers]

                if isinstance(offers, list):
                    result["offers"] += len(
                        [x for x in offers if isinstance(x, dict)]
                    )

            graph = item.get("@graph")

            if isinstance(graph, list):
                stack.extend(graph)

    return result


def parallel_fetch(urls: list[str]) -> dict[str, dict]:
    results = {}

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(request, requests.Session(), url): url
            for url in dict.fromkeys(urls)
        }

        for future in as_completed(futures):
            url = futures[future]

            try:
                results[url] = future.result()
            except Exception as exc:
                results[url] = {
                    "ok": False,
                    "status": None,
                    "url": url,
                    "bytes": 0,
                    "html": "",
                    "elapsed": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                }

    return results


def run_fast_diagnostic() -> dict:
    started = time.time()

    # ------------------------------------------------------------
    # 1. Current production discovery surface:
    #    /chercher.html?q=Born+in+Roma, pages 1..10.
    #    Pages are fetched IN PARALLEL, unlike production search().
    # ------------------------------------------------------------
    search_urls = []

    for page in range(1, 11):
        if page == 1:
            search_urls.append(
                f"{BASE}/chercher.html?q={quote_plus('Born in Roma')}"
            )
        else:
            search_urls.append(
                f"{BASE}/chercher.html?q={quote_plus('Born in Roma')}"
                f"&page={page}"
            )

    search_responses = parallel_fetch(search_urls)

    search_pages = []
    search_products = set()

    for page, url in enumerate(search_urls, 1):
        response = search_responses.get(url, {})

        urls = extract_product_urls(response.get("html", ""))

        born = {
            x for x in urls
            if is_born_product(x)
        }

        search_products.update(born)

        search_pages.append({
            "page": page,
            "requested_url": url,
            "final_url": response.get("url"),
            "status": response.get("status"),
            "bytes": response.get("bytes", 0),
            "elapsed": response.get("elapsed"),
            "born_urls": sorted(born),
            "error": response.get("error"),
        })

    # ------------------------------------------------------------
    # 2. Category discovery.
    # ------------------------------------------------------------
    category_urls = []

    for target in TARGETS:
        category_urls.extend(target["categories"])

    category_responses = parallel_fetch(category_urls)

    category_products = set()
    category_pages = []

    for url in dict.fromkeys(category_urls):
        response = category_responses.get(url, {})
        urls = extract_product_urls(response.get("html", ""))

        born = {
            x for x in urls
            if is_born_product(x)
        }

        category_products.update(born)

        category_pages.append({
            "requested_url": url,
            "final_url": response.get("url"),
            "status": response.get("status"),
            "bytes": response.get("bytes", 0),
            "elapsed": response.get("elapsed"),
            "born_urls": sorted(born),
            "error": response.get("error"),
        })

    # ------------------------------------------------------------
    # 3. Exact alias searches.
    #    One page per alias, all aliases in parallel.
    # ------------------------------------------------------------
    alias_jobs = []

    for target in TARGETS:
        for alias in target["aliases"]:
            alias_jobs.append(
                (
                    target["canonical"],
                    alias,
                    f"{BASE}/chercher.html?q={quote_plus(alias)}",
                )
            )

    alias_responses = parallel_fetch(
        [job[2] for job in alias_jobs]
    )

    # ------------------------------------------------------------
    # 4. Build target-specific candidate sets.
    # ------------------------------------------------------------
    all_discovered = sorted(
        search_products | category_products
    )

    target_results = {}

    for target in TARGETS:
        alias_results = []
        alias_products = set()

        for canonical, alias, url in alias_jobs:
            if canonical != target["canonical"]:
                continue

            response = alias_responses.get(url, {})
            products = {
                x for x in extract_product_urls(
                    response.get("html", "")
                )
                if is_born_product(x)
            }

            alias_products.update(products)

            alias_results.append({
                "query": alias,
                "requested_url": url,
                "final_url": response.get("url"),
                "status": response.get("status"),
                "bytes": response.get("bytes", 0),
                "elapsed": response.get("elapsed"),
                "urls": sorted(products),
                "error": response.get("error"),
            })

        candidates = target_candidates(
            sorted(set(all_discovered) | alias_products),
            target,
        )

        # Only parse the top two candidate product pages.
        parsed = []

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [
                pool.submit(
                    parse_product_page,
                    requests.Session(),
                    item["url"],
                    target,
                )
                for item in candidates[:2]
            ]

            for future in futures:
                try:
                    parsed.append(future.result())
                except Exception as exc:
                    parsed.append({
                        "error": f"{type(exc).__name__}: {exc}"
                    })

        target_results[target["canonical"]] = {
            "found_candidate": bool(candidates),
            "candidate_url_matches": candidates,
            "direct_product_parse": parsed,
            "exact_alias_search": alias_results,
        }

    return {
        "diagnostic": "deloox-born-in-roma-4-targets-fast-v3",
        "read_only": True,
        "production_search_called": False,
        "targets": [x["canonical"] for x in TARGETS],
        "search_surface": {
            "pages_checked": 10,
            "born_product_url_count": len(search_products),
            "born_product_urls": sorted(search_products),
            "pages": search_pages,
        },
        "category_surface": {
            "pages_checked": len(set(category_urls)),
            "born_product_url_count": len(category_products),
            "born_product_urls": sorted(category_products),
            "pages": category_pages,
        },
        "target_results": target_results,
        "timing_seconds": round(time.time() - started, 2),
    }


@router.get("/diagnose-deloox-born4")
def diagnose_deloox_born4():
    return run_fast_diagnostic()


if __name__ == "__main__":
    print(
        json.dumps(
            run_fast_diagnostic(),
            ensure_ascii=False,
            indent=2,
        )
    )
