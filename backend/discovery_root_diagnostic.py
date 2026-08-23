from __future__ import annotations

import importlib
import json
import re
import traceback
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException

app = FastAPI(title="ScentHunter Discovery Root Diagnostic", version="1.0")

TIMEOUT = 20
READER_TIMEOUT = 20
READER_BASE = "https://r.jina.ai/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9,nl-NL,nl;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

STORES = {
    "notino": {
        "module": "scrapers.notino.scraper",
        "base": "https://www.notino.fr",
        "search_urls": lambda q: [
            f"https://www.notino.fr/search.asp?exps={quote_plus(q)}",
            f"https://www.notino.fr/search?query={quote_plus(q)}",
        ],
        "product_selector": 'a[href*="/"]',
        "sitemap": "https://www.notino.fr/sitemap.xml",
        "reader": True,
    },
    "perfumemarket": {
        "module": "scrapers.perfumemarket.scraper",
        "base": "https://www.perfumemarket.nl",
        "search_urls": lambda q: [
            f"https://www.perfumemarket.nl/nl/search?q={quote_plus(q)}",
            f"https://www.perfumemarket.nl/search?q={quote_plus(q)}",
        ],
        "product_selector": 'a[href*="/products/"]',
        "sitemap": "https://www.perfumemarket.nl/sitemap.xml",
        "reader": False,
    },
    "parfumcity": {
        "module": "scrapers.parfumcity.scraper",
        "base": "https://www.parfumcity.nl",
        "search_urls": lambda q: [
            f"https://www.parfumcity.nl/search?q={quote_plus(q)}",
            f"https://www.parfumcity.nl/nl/search?q={quote_plus(q)}",
        ],
        "product_selector": 'a[href*="/products/"]',
        "sitemap": "https://www.parfumcity.nl/sitemap.xml",
        "reader": False,
    },
}


def clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value: Any) -> str:
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", clean(value).lower()),
    ).strip()


def tokens(value: Any) -> List[str]:
    return [x for x in norm(value).split() if len(x) > 1]


def token_hits(text: str, query: str) -> Dict[str, bool]:
    hay = set(tokens(text))
    return {token: token in hay for token in tokens(query)}


def product_links(soup: BeautifulSoup, base: str) -> List[Dict[str, Any]]:
    out = []
    seen = set()

    for a in soup.find_all("a", href=True):
        href = clean(a.get("href"))
        if not href:
            continue

        url = urljoin(base, href).split("?")[0].split("#")[0]
        parsed = urlparse(url)

        if parsed.netloc.lower() not in {
            urlparse(base).netloc.lower(),
            "www." + urlparse(base).netloc.lower().removeprefix("www."),
        }:
            continue

        if url in seen:
            continue

        path = parsed.path.lower()

        # Store-generic product URL signals.
        looks_product = (
            "/products/" in path
            or "/product/" in path
            or bool(re.search(r"/p-\d+(?:/|$)", path))
        )
        if not looks_product:
            continue

        seen.add(url)

        anchor = clean(a.get_text(" ", strip=True))
        node = a
        best = anchor

        for _ in range(8):
            node = getattr(node, "parent", None)
            if node is None:
                break
            text = clean(node.get_text(" ", strip=True))
            if len(text) > len(best):
                best = text
            if len(text) >= 40:
                break

        out.append({
            "url": url,
            "anchor": anchor[:250],
            "context": best[:700],
        })

    return out


def inspect_module(store: str) -> Dict[str, Any]:
    cfg = STORES[store]
    result = {
        "module": cfg["module"],
        "loaded": False,
        "file": None,
        "functions": {},
        "error": None,
    }

    try:
        module = importlib.import_module(cfg["module"])
        result["loaded"] = True
        result["file"] = getattr(module, "__file__", None)

        for name in (
            "search",
            "scrape",
            "diagnose",
            "debug_search",
            "_search_http_candidates",
            "_reader_discovery",
            "_sitemap_discovery",
            "search_page_urls",
            "sitemap",
        ):
            result["functions"][name] = callable(getattr(module, name, None))

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"

    return result


def raw_search_probe(store: str, query: str) -> Dict[str, Any]:
    cfg = STORES[store]
    session = requests.Session()
    session.headers.update(HEADERS)

    pages = []

    try:
        for search_url in cfg["search_urls"](query):
            item = {
                "url": search_url,
                "status": None,
                "final_url": None,
                "html_length": 0,
                "error": None,
                "query_occurrences": 0,
                "token_hits": {},
                "product_link_count": 0,
                "matching_product_link_count": 0,
                "matching_samples": [],
                "challenge": False,
            }

            try:
                response = session.get(
                    search_url,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )
                text = response.text or ""
                item.update({
                    "status": response.status_code,
                    "final_url": response.url,
                    "html_length": len(text),
                    "query_occurrences": text.lower().count(query.lower()),
                    "token_hits": token_hits(text, query),
                    "challenge": any(
                        marker in text.lower()
                        for marker in (
                            "just a moment",
                            "cf-chl-",
                            "challenge-platform",
                            "verify you are human",
                            "enable javascript and cookies",
                        )
                    ),
                })

                if response.status_code == 200:
                    soup = BeautifulSoup(text, "html.parser")
                    links = product_links(soup, cfg["base"])
                    item["product_link_count"] = len(links)

                    matching = [
                        x for x in links
                        if all(
                            hit
                            for hit in token_hits(
                                f'{x["anchor"]} {x["context"]} {x["url"]}',
                                query,
                            ).values()
                        )
                    ]

                    item["matching_product_link_count"] = len(matching)
                    item["matching_samples"] = matching[:10]

            except requests.RequestException as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"

            pages.append(item)

        return {
            "search_pages": pages,
            "any_http_success": any(x["status"] == 200 for x in pages),
            "any_product_links": any(x["product_link_count"] > 0 for x in pages),
            "any_matching_links": any(
                x["matching_product_link_count"] > 0 for x in pages
            ),
        }
    finally:
        session.close()


def reader_probe(store: str, query: str) -> Optional[Dict[str, Any]]:
    cfg = STORES[store]

    if not cfg.get("reader"):
        return None

    session = requests.Session()
    session.headers.update(HEADERS)

    pages = []

    try:
        for search_url in cfg["search_urls"](query):
            reader_url = READER_BASE + search_url
            item = {
                "source_url": search_url,
                "reader_url": reader_url,
                "status": None,
                "html_length": 0,
                "error": None,
                "query_occurrences": 0,
                "product_url_count": 0,
                "query_matching_url_count": 0,
                "samples": [],
            }

            try:
                response = session.get(
                    reader_url,
                    timeout=READER_TIMEOUT,
                    allow_redirects=True,
                )
                text = response.text or ""
                item.update({
                    "status": response.status_code,
                    "html_length": len(text),
                    "query_occurrences": text.lower().count(query.lower()),
                })

                urls = set()

                for match in re.finditer(
                    r"https?://(?:www\.)?notino\.fr/[^\s<>)\]\"']+",
                    text,
                    re.I,
                ):
                    urls.add(match.group(0).rstrip(".,;)"))

                markdown = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
                for match in markdown.finditer(text):
                    raw = match.group(1)
                    if raw.startswith("/"):
                        urls.add(urljoin(cfg["base"], raw))
                    elif "notino.fr/" in raw:
                        urls.add(raw)

                product_urls = [
                    u for u in urls
                    if re.search(r"notino\.fr/.+", u, re.I)
                ]

                matching = [
                    u for u in product_urls
                    if all(token in norm(u) for token in tokens(query))
                ]

                item["product_url_count"] = len(product_urls)
                item["query_matching_url_count"] = len(matching)
                item["samples"] = matching[:15]

            except requests.RequestException as exc:
                item["error"] = f"{type(exc).__name__}: {exc}"

            pages.append(item)

        return {
            "pages": pages,
            "any_matching_urls": any(
                x["query_matching_url_count"] > 0 for x in pages
            ),
        }
    finally:
        session.close()


def sitemap_probe(store: str, query: str) -> Dict[str, Any]:
    cfg = STORES[store]
    session = requests.Session()
    session.headers.update(HEADERS)

    result = {
        "url": cfg["sitemap"],
        "status": None,
        "html_length": 0,
        "error": None,
        "root_type": None,
        "loc_count": 0,
        "child_sitemaps": 0,
        "query_matching_urls": 0,
        "samples": [],
    }

    try:
        try:
            response = session.get(
                cfg["sitemap"],
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            text = response.text or ""
            result["status"] = response.status_code
            result["html_length"] = len(text)

            if response.status_code != 200:
                return result

        except requests.RequestException as exc:
            result["error"] = f"{type(exc).__name__}: {exc}"
            return result

        soup = BeautifulSoup(text, "xml")
        locs = [
            clean(x.get_text())
            for x in soup.find_all("loc")
            if clean(x.get_text())
        ]

        result["loc_count"] = len(locs)

        low = text.lower()
        if "<sitemapindex" in low:
            result["root_type"] = "sitemapindex"
        elif "<urlset" in low:
            result["root_type"] = "urlset"
        else:
            result["root_type"] = "unknown"

        children = [
            u for u in locs
            if u.lower().endswith(".xml") or "sitemap" in u.lower()
        ]
        result["child_sitemaps"] = len(children)

        matching = [
            u for u in locs
            if all(token in norm(u) for token in tokens(query))
        ]
        result["query_matching_urls"] = len(matching)
        result["samples"] = matching[:20]

        # For sitemap indexes, inspect a limited number of child maps.
        if not matching and children:
            inspected = 0
            child_matches = []

            for child_url in children[:20]:
                inspected += 1
                try:
                    child = session.get(
                        child_url,
                        timeout=TIMEOUT,
                        allow_redirects=True,
                    )
                    if child.status_code != 200:
                        continue

                    child_soup = BeautifulSoup(
                        child.text or "",
                        "xml",
                    )
                    child_locs = [
                        clean(x.get_text())
                        for x in child_soup.find_all("loc")
                        if clean(x.get_text())
                    ]

                    for u in child_locs:
                        if all(
                            token in norm(u)
                            for token in tokens(query)
                        ):
                            child_matches.append(u)

                    if len(child_matches) >= 20:
                        break

                except requests.RequestException:
                    continue

            result["child_sitemaps_inspected"] = inspected
            result["child_query_matching_urls"] = len(child_matches)
            result["child_samples"] = child_matches[:20]

        return result

    finally:
        session.close()


def run_current_scraper(store: str, query: str) -> Dict[str, Any]:
    cfg = STORES[store]
    result = {
        "attempted": False,
        "count": None,
        "results": [],
        "error": None,
    }

    try:
        module = importlib.import_module(cfg["module"])
        search_fn = getattr(module, "search", None)

        if not callable(search_fn):
            result["error"] = "search_function_missing"
            return result

        result["attempted"] = True
        data = search_fn(query)

        if isinstance(data, list):
            result["count"] = len(data)
            result["results"] = data[:10]
        else:
            result["count"] = None
            result["results_type"] = type(data).__name__

    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["traceback"] = traceback.format_exc()

    return result


def classify(store: str, raw: Dict[str, Any], reader: Any,
             sitemap: Dict[str, Any], scraper: Dict[str, Any]) -> List[str]:
    findings = []

    if not raw["any_http_success"]:
        findings.append(
            "SEARCH_TRANSPORT: nessun endpoint di ricerca ha risposto HTTP 200."
        )
        return findings

    if raw["any_product_links"] and not raw["any_matching_links"]:
        findings.append(
            "SEARCH_SELECTOR_OR_MATCHING: la pagina contiene link prodotto, "
            "ma nessun card/link contiene tutti i token della query."
        )

    if not raw["any_product_links"]:
        findings.append(
            "SEARCH_DISCOVERY: la risposta HTML non contiene link prodotto "
            "riconoscibili. Probabile problema di endpoint, rendering, "
            "struttura HTML o canale di discovery."
        )

    if raw["any_matching_links"] and scraper.get("count") == 0:
        findings.append(
            "POST_DISCOVERY: esistono candidati che corrispondono alla query, "
            "ma il current scraper restituisce 0. Il problema è dopo la discovery "
            "(product page, validation, price/stock o matcher)."
        )

    if scraper.get("count", None) not in (None, 0):
        findings.append(
            "SCRAPER_OK: il current scraper produce almeno un risultato."
        )

    if reader and not reader.get("any_matching_urls") and not raw["any_matching_links"]:
        findings.append(
            "READER_EMPTY: anche il canale Jina/reader non espone URL "
            "corrispondenti alla query."
        )

    sitemap_matches = sitemap.get("query_matching_urls", 0)
    child_matches = sitemap.get("child_query_matching_urls", 0)

    if (sitemap_matches or child_matches) and scraper.get("count") == 0:
        findings.append(
            "SITEMAP_VS_SCRAPER: la sitemap contiene URL compatibili con la query "
            "ma il current scraper non li trasforma in risultati."
        )

    if not sitemap_matches and not child_matches:
        findings.append(
            "SITEMAP_NO_MATCH: nessun URL della sitemap analizzata contiene "
            "tutti i token della query. Questo non prova che il prodotto non esista: "
            "può usare uno slug diverso."
        )

    return findings


@app.get("/")
def root():
    return {
        "ok": True,
        "diagnostic": "ScentHunter discovery root diagnostic",
        "stores": list(STORES),
        "usage": "/diagnose?store=notino&q=Hawas%20Ice",
    }


@app.get("/diagnose")
def diagnose(store: str, q: str):
    store = clean(store).lower()
    query = clean(q)

    if store not in STORES:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unknown_store",
                "allowed": list(STORES),
            },
        )

    if not query:
        raise HTTPException(status_code=400, detail="empty_query")

    module = inspect_module(store)
    raw = raw_search_probe(store, query)
    reader = reader_probe(store, query)
    sitemap = sitemap_probe(store, query)
    scraper = run_current_scraper(store, query)

    findings = classify(
        store,
        raw,
        reader,
        sitemap,
        scraper,
    )

    return {
        "diagnostic": True,
        "store": store,
        "query": query,
        "module": module,
        "raw_search_probe": raw,
        "reader_probe": reader,
        "sitemap_probe": sitemap,
        "current_scraper": scraper,
        "findings": findings,
    }


@app.get("/diagnose-all")
def diagnose_all(q: str):
    query = clean(q)
    if not query:
        raise HTTPException(status_code=400, detail="empty_query")

    return {
        "diagnostic": True,
        "query": query,
        "stores": {
            store: diagnose(store, query)
            for store in STORES
        },
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("store", nargs="?")
    parser.add_argument("query", nargs="?")
    args = parser.parse_args()

    if not args.store or not args.query:
        print(
            json.dumps(
                {
                    "usage": (
                        "python discovery_root_diagnostic.py "
                        "notino 'Hawas Ice'"
                    )
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(
            json.dumps(
                diagnose(args.store, args.query),
                ensure_ascii=False,
                indent=2,
            )
        )
