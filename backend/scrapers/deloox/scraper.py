"""
Deloox discovery diagnostic V3 for ScentHunter.

Purpose:
    Diagnose exactly why a Deloox.be perfume disappears during discovery.

This file is READ-ONLY with respect to Deloox and ScentHunter:
    - it performs GET requests only;
    - it never writes to Deloox;
    - it never modifies the production scraper;
    - it does not hard-code any perfume/category/product id.

It analyzes:
    1. HTTP response metadata and raw HTML size
    2. every relevant <a> around the query
    3. all category URLs and product URLs present in the page
    4. raw regex URL extraction
    5. escaped JSON/JS URLs
    6. JSON/JS objects around the query
    7. numeric ids near the query
    8. exact query occurrences and bounded HTML snippets
    9. the production scraper's own discovery functions, when importable
   10. disagreements between raw HTML evidence and scraper output

Run:
    python deloox_diagnostic_v3.py "Liquid Brun"

Optional:
    python deloox_diagnostic_v3.py "Liquid Brun" --output deloox_v3.json
    python deloox_diagnostic_v3.py "Liquid Brun" --timeout 15
"""

from __future__ import annotations

import argparse
import ast
import html as htmllib
import importlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BASE_URL = "https://www.deloox.be"
TIMEOUT = 10

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

CATEGORY_ROOTS = [
    f"{BASE_URL}/categorie/1075732/parfum-homme.html",
    f"{BASE_URL}/categorie/1000063/parfum-femme.html",
    f"{BASE_URL}/categorie/1075918/parfum-mixte.html",
]

URL_RE = re.compile(
    r"https?://(?:www\.)?deloox\.be/[^\s\"'<>\\]+"
    r"|(?<![A-Za-z0-9])/(?:en/|it/|nl/|fr/)?"
    r"[^\s\"'<>\\]+",
    re.I,
)

CATEGORY_PATH_RE = re.compile(
    r"/(?:en/|it/|nl/|fr/)?(?:category|categoria|categorie)/"
    r"\d+/[^\"'<>\\\s]+?\.html",
    re.I,
)

PRODUCT_PATH_RE = re.compile(
    r"/(?:en/|it/|nl/|fr/)?(?:product|produit)/"
    r"\d+/[^\"'<>\\\s]+",
    re.I,
)

ID_FIELD_RE = re.compile(
    r'(?P<field>'
    r'categoryId|category_id|productLineId|product_line_id|'
    r'productLineID|product_line_ID|data-category-id|data-product-line-id'
    r')'
    r'\s*[:=]\s*["\']?(?P<id>\d{3,})',
    re.I,
)

QUERY_TOKEN_SPLIT_RE = re.compile(r"[^\w]+", re.UNICODE)


def clean(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def tokens(value: object) -> set[str]:
    return {x.casefold() for x in QUERY_TOKEN_SPLIT_RE.split(clean(value)) if x}


def normalize_url(raw: object) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""

    for _ in range(4):
        value = (
            value.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\x2F", "/")
            .replace("\\x2f", "/")
        )

    value = htmllib.unescape(value)
    value = value.strip("\"'()[]{}<>,;")

    if value.startswith("//"):
        value = "https:" + value

    url = urljoin(BASE_URL, value)
    parsed = urlparse(url)

    if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
        return ""

    return url.split("#", 1)[0].split("?", 1)[0]


def safe_excerpt(text: str, start: int, end: int, radius: int = 900) -> str:
    lo = max(0, start - radius)
    hi = min(len(text), end + radius)
    return text[lo:hi]


def find_occurrences(text: str, query: str, limit: int = 30) -> list[dict]:
    result = []
    q = clean(query)
    if not q:
        return result

    lower = text.casefold()
    q_lower = q.casefold()
    pos = 0

    while len(result) < limit:
        idx = lower.find(q_lower, pos)
        if idx < 0:
            break
        result.append(
            {
                "offset": idx,
                "match": text[idx : idx + len(q)],
                "snippet": safe_excerpt(text, idx, idx + len(q)),
            }
        )
        pos = idx + max(1, len(q))

    # Also search individual tokens because markup/JSON often splits the name.
    query_tokens = sorted(tokens(q), key=len, reverse=True)
    for token in query_tokens:
        if len(result) >= limit:
            break
        pos = 0
        while len(result) < limit:
            idx = lower.find(token, pos)
            if idx < 0:
                break
            result.append(
                {
                    "offset": idx,
                    "match": text[idx : idx + len(token)],
                    "token": token,
                    "snippet": safe_excerpt(text, idx, idx + len(token), 500),
                }
            )
            pos = idx + max(1, len(token))

    # De-duplicate by offset.
    dedup = {}
    for item in result:
        dedup[item["offset"]] = item
    return sorted(dedup.values(), key=lambda x: x["offset"])[:limit]


def extract_urls_by_regex(raw: str, query: str) -> dict:
    normalized = raw
    for _ in range(4):
        normalized = (
            normalized.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\x2F", "/")
            .replace("\\x2f", "/")
        )
    normalized = htmllib.unescape(normalized)

    categories = []
    products = []
    all_deloox = []

    for match in URL_RE.finditer(normalized):
        value = normalize_url(match.group(0))
        if not value:
            continue
        if value not in all_deloox:
            all_deloox.append(value)

        path = urlparse(value).path
        if CATEGORY_PATH_RE.search(path) and value not in categories:
            categories.append(value)
        if PRODUCT_PATH_RE.search(path) and value not in products:
            products.append(value)

    q_tokens = tokens(query)

    def relevant(url: str) -> bool:
        return q_tokens.issubset(tokens(url))

    return {
        "all_deloox_urls_count": len(all_deloox),
        "category_urls_count": len(categories),
        "product_urls_count": len(products),
        "category_urls_matching_query": [x for x in categories if relevant(x)][:100],
        "product_urls_matching_query": [x for x in products if relevant(x)][:100],
        "category_urls_sample": categories[:100],
        "product_urls_sample": products[:100],
    }


def inspect_dom(raw: str, query: str) -> dict:
    soup = BeautifulSoup(raw, "html.parser")
    q_tokens = tokens(query)

    anchors = soup.find_all("a", href=True)
    relevant_anchors = []
    all_categories = []
    all_products = []

    for a in anchors:
        href = clean(a.get("href"))
        text = clean(a.get_text(" ", strip=True))
        attrs = {
            k: clean(v) if not isinstance(v, list) else [clean(x) for x in v]
            for k, v in a.attrs.items()
            if k in {
                "href",
                "class",
                "id",
                "data-category-id",
                "data-product-line-id",
                "data-id",
                "data-testid",
                "aria-label",
                "title",
            }
        }

        url = normalize_url(href)
        combined = f"{text} {href} {json.dumps(attrs, ensure_ascii=False)}"

        if q_tokens and q_tokens.issubset(tokens(combined)):
            relevant_anchors.append(
                {
                    "text": text[:500],
                    "href": href[:1000],
                    "normalized_url": url,
                    "attrs": attrs,
                }
            )

        if url:
            path = urlparse(url).path
            if CATEGORY_PATH_RE.search(path) and url not in all_categories:
                all_categories.append(url)
            if PRODUCT_PATH_RE.search(path) and url not in all_products:
                all_products.append(url)

    # Look beyond anchors: elements containing both query tokens and useful
    # id/url attributes are often where the current site hides filters.
    relevant_nodes = []
    for node in soup.find_all(True):
        text = clean(node.get_text(" ", strip=True))
        attr_blob = " ".join(
            f"{k}={clean(v)}" for k, v in node.attrs.items()
        )
        combined = f"{text} {attr_blob}"
        if q_tokens and q_tokens.issubset(tokens(combined)):
            if any(
                key in attr_blob.casefold()
                for key in (
                    "category",
                    "productline",
                    "product_line",
                    "data-id",
                    "href=",
                )
            ):
                relevant_nodes.append(
                    {
                        "tag": node.name,
                        "text": text[:700],
                        "attrs": {
                            k: clean(v) if not isinstance(v, list) else [
                                clean(x) for x in v
                            ]
                            for k, v in node.attrs.items()
                        },
                    }
                )
                if len(relevant_nodes) >= 100:
                    break

    scripts = soup.find_all("script")
    script_query_hits = []
    for i, script in enumerate(scripts):
        content = script.string or script.get_text() or ""
        if q_tokens and q_tokens.issubset(tokens(content)):
            script_query_hits.append(
                {
                    "index": i,
                    "type": script.get("type"),
                    "id": script.get("id"),
                    "bytes": len(content),
                    "snippets": find_occurrences(content, query, 8),
                }
            )

    return {
        "html_parser": "BeautifulSoup(html.parser)",
        "anchor_count": len(anchors),
        "relevant_anchor_count": len(relevant_anchors),
        "relevant_anchors": relevant_anchors[:100],
        "all_category_urls_count": len(all_categories),
        "all_product_urls_count": len(all_products),
        "all_category_urls_sample": all_categories[:100],
        "all_product_urls_sample": all_products[:100],
        "relevant_nodes_count": len(relevant_nodes),
        "relevant_nodes": relevant_nodes[:100],
        "script_count": len(scripts),
        "scripts_containing_query": script_query_hits[:50],
    }


def inspect_json_js(raw: str, query: str) -> dict:
    decoded = raw
    for _ in range(5):
        decoded = (
            decoded.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\x2F", "/")
            .replace("\\x2f", "/")
        )
    decoded = htmllib.unescape(decoded)

    occurrences = find_occurrences(decoded, query, 30)

    id_hits = []
    for match in ID_FIELD_RE.finditer(decoded):
        start = max(0, match.start() - 1000)
        end = min(len(decoded), match.end() + 1000)
        window = decoded[start:end]
        if tokens(query) & tokens(window):
            id_hits.append(
                {
                    "field": match.group("field"),
                    "id": match.group("id"),
                    "offset": match.start(),
                    "snippet": window,
                }
            )

    # Generic JSON-ish objects/arrays around the query. This intentionally
    # does not assume a specific frontend framework.
    object_windows = []
    for occ in occurrences[:20]:
        idx = occ["offset"]
        left = decoded.rfind("{", max(0, idx - 10000), idx)
        right = decoded.find("}", idx, min(len(decoded), idx + 10000))
        if left >= 0 and right >= 0 and right > left:
            object_windows.append(
                {
                    "offset": idx,
                    "object_like": decoded[left : right + 1][:20000],
                }
            )

    # Direct URL-like strings close to each query occurrence.
    nearby_urls = []
    for occ in occurrences[:30]:
        idx = occ["offset"]
        window = decoded[max(0, idx - 8000) : min(len(decoded), idx + 8000)]
        urls = []
        for match in CATEGORY_PATH_RE.finditer(window):
            value = normalize_url(match.group(0))
            if value and value not in urls:
                urls.append(value)
        for match in PRODUCT_PATH_RE.finditer(window):
            value = normalize_url(match.group(0))
            if value and value not in urls:
                urls.append(value)
        if urls:
            nearby_urls.append(
                {
                    "query_offset": idx,
                    "urls": urls[:100],
                }
            )

    return {
        "decoded_bytes": len(decoded),
        "query_occurrences": occurrences,
        "query_occurrence_count": len(occurrences),
        "id_field_hits_near_query": id_hits[:100],
        "object_like_windows": object_windows[:50],
        "urls_near_query": nearby_urls[:100],
    }


def compare_with_production_scraper(raw: str, query: str) -> dict:
    """
    Import the production scraper if it is available in the same environment.

    We call only the two discovery helpers. No network call is made here and
    no production state is changed.
    """
    candidates = [
        "backend.scrapers.deloox.scraper",
        "scrapers.deloox.scraper",
        "scrapers.Deloox.scraper",
    ]

    module = None
    import_errors = []

    for name in candidates:
        try:
            module = importlib.import_module(name)
            break
        except Exception as exc:
            import_errors.append(f"{name}: {type(exc).__name__}: {exc}")

    if module is None:
        return {
            "imported": False,
            "import_errors": import_errors,
            "candidate_product_urls": None,
            "category_product_line_links": None,
        }

    report = {
        "imported": True,
        "module": module.__name__,
        "candidate_product_urls": None,
        "category_product_line_links": None,
        "errors": [],
    }

    fn = getattr(module, "_candidate_product_urls", None)
    if callable(fn):
        try:
            started = time.perf_counter()
            value = fn(raw, query)
            elapsed = time.perf_counter() - started
            report["candidate_product_urls"] = {
                "count": len(value) if isinstance(value, (list, tuple, set)) else None,
                "value": list(value)[:100] if isinstance(value, (list, tuple, set)) else repr(value),
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as exc:
            report["errors"].append(
                f"_candidate_product_urls: {type(exc).__name__}: {exc}"
            )
    else:
        report["errors"].append("_candidate_product_urls not found")

    fn = getattr(module, "_category_product_line_links", None)
    if callable(fn):
        try:
            started = time.perf_counter()
            value = fn(raw, query)
            elapsed = time.perf_counter() - started
            report["category_product_line_links"] = {
                "count": len(value) if isinstance(value, (list, tuple, set)) else None,
                "value": list(value)[:100] if isinstance(value, (list, tuple, set)) else repr(value),
                "elapsed_seconds": round(elapsed, 4),
            }
        except Exception as exc:
            report["errors"].append(
                f"_category_product_line_links: {type(exc).__name__}: {exc}"
            )
    else:
        report["errors"].append("_category_product_line_links not found")

    return report


def inspect_source_file(path: str | None) -> dict:
    if not path:
        return {"provided": False}

    p = Path(path)
    if not p.exists():
        return {"provided": True, "exists": False, "path": str(p)}

    source = p.read_text(encoding="utf-8")
    findings = {
        "provided": True,
        "exists": True,
        "path": str(p),
        "lines": len(source.splitlines()),
        "bytes": len(source.encode("utf-8")),
        "contains_forbidden_domains": bool(
            re.search(r"deloox\.(?:com|nl)", source, re.I)
        ),
        "contains_hardcoded_liquid_brun_id": bool(
            re.search(r"1122039|1355229", source)
        ),
    }

    try:
        ast.parse(source)
        findings["ast_parse"] = "OK"
    except SyntaxError as exc:
        findings["ast_parse"] = f"FAIL: {exc}"

    return findings


def fetch(session: requests.Session, url: str, timeout: int) -> dict:
    started = time.perf_counter()
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=timeout,
            allow_redirects=True,
        )
    except Exception as exc:
        return {
            "url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "elapsed_seconds": round(time.perf_counter() - started, 3),
        }

    raw = response.text or ""
    return {
        "url": url,
        "final_url": response.url,
        "status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "content_encoding": response.headers.get("content-encoding"),
        "server": response.headers.get("server"),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "bytes_text": len(raw),
        "raw_html": raw,
    }


def analyze_page(page: dict, query: str) -> dict:
    raw = page.get("raw_html", "")
    if not raw:
        return {
            "request": {k: v for k, v in page.items() if k != "raw_html"},
            "analysis_skipped": True,
        }

    regex = extract_urls_by_regex(raw, query)
    dom = inspect_dom(raw, query)
    js = inspect_json_js(raw, query)
    production = compare_with_production_scraper(raw, query)

    all_product_urls = (
        dom["all_product_urls_sample"]
        + regex["product_urls_sample"]
    )
    dedup_products = []
    for url in all_product_urls:
        if url not in dedup_products:
            dedup_products.append(url)

    all_category_urls = (
        dom["all_category_urls_sample"]
        + regex["category_urls_sample"]
    )
    dedup_categories = []
    for url in all_category_urls:
        if url not in dedup_categories:
            dedup_categories.append(url)

    q_tokens = tokens(query)

    def query_in_url(url: str) -> bool:
        return q_tokens.issubset(tokens(url))

    return {
        "request": {k: v for k, v in page.items() if k != "raw_html"},
        "query": query,
        "query_tokens": sorted(q_tokens),
        "query_found_case_insensitive": clean(query).casefold() in raw.casefold(),
        "query_occurrences": find_occurrences(raw, query, 30),
        "regex": regex,
        "dom": dom,
        "json_js": js,
        "production_scraper": production,
        "cross_check": {
            "unique_product_urls_seen_anywhere": dedup_products[:200],
            "unique_category_urls_seen_anywhere": dedup_categories[:200],
            "product_urls_containing_query": [
                x for x in dedup_products if query_in_url(x)
            ],
            "category_urls_containing_query": [
                x for x in dedup_categories if query_in_url(x)
            ],
            "raw_has_product_urls": bool(dedup_products),
            "raw_has_category_urls": bool(dedup_categories),
            "production_candidate_zero_but_raw_product_exists": (
                bool(dedup_products)
                and production.get("candidate_product_urls", {}).get("count") == 0
                if isinstance(production.get("candidate_product_urls"), dict)
                else False
            ),
            "production_line_zero_but_raw_category_exists": (
                bool(dedup_categories)
                and production.get("category_product_line_links", {}).get("count") == 0
                if isinstance(production.get("category_product_line_links"), dict)
                else False
            ),
        },
    }


def build_summary(report: dict) -> list[str]:
    conclusions = []

    pages = report.get("pages", [])
    any_query = any(p.get("query_found_case_insensitive") for p in pages)
    any_product = any(
        p.get("cross_check", {}).get("raw_has_product_urls")
        for p in pages
    )
    any_category = any(
        p.get("cross_check", {}).get("raw_has_category_urls")
        for p in pages
    )
    any_matching_category = any(
        p.get("cross_check", {}).get("category_urls_containing_query")
        for p in pages
    )
    any_matching_product = any(
        p.get("cross_check", {}).get("product_urls_containing_query")
        for p in pages
    )
    production_candidate_zero = any(
        (
            isinstance(p.get("production_scraper", {}).get("candidate_product_urls"), dict)
            and p["production_scraper"]["candidate_product_urls"].get("count") == 0
        )
        for p in pages
    )
    production_line_zero = any(
        (
            isinstance(p.get("production_scraper", {}).get("category_product_line_links"), dict)
            and p["production_scraper"]["category_product_line_links"].get("count") == 0
        )
        for p in pages
    )

    if not any_query:
        conclusions.append(
            "A: the requested text is not present in the raw HTML fetched by this environment."
        )
    elif any_matching_product:
        conclusions.append(
            "B: at least one product URL containing the query exists in raw HTML; discovery filtering is the prime suspect."
        )
    elif any_matching_category:
        conclusions.append(
            "C: a matching Product Line/category URL exists in raw HTML; category-link extraction is the prime suspect."
        )
    elif any_product and production_candidate_zero:
        conclusions.append(
            "D: product URLs exist in the raw page but production _candidate_product_urls returns zero."
        )
    elif any_category and production_line_zero:
        conclusions.append(
            "E: category URLs exist in the raw page but production _category_product_line_links returns zero."
        )
    elif any_query:
        conclusions.append(
            "F: query text exists, but no directly matching category/product URL was found; inspect JSON/JS/id evidence next."
        )

    if not any_product and not any_category and any_query:
        conclusions.append(
            "The page may render the useful links only after client-side JavaScript, or the URLs may be stored in a non-URL data structure."
        )

    return conclusions


def main() -> int:
    parser = argparse.ArgumentParser(description="Deloox.be discovery diagnostic V3")
    parser.add_argument("query", nargs="?", default="Liquid Brun")
    parser.add_argument(
        "--output",
        default="deloox_diagnostic_v3.json",
        help="JSON report path",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=TIMEOUT,
    )
    parser.add_argument(
        "--scraper",
        default=None,
        help="Optional path to the production scraper source for static checks",
    )
    parser.add_argument(
        "--no-production-import",
        action="store_true",
        help="Do not import the local production scraper",
    )
    args = parser.parse_args()

    report = {
        "diagnostic": "Deloox discovery V3",
        "version": 3,
        "timestamp_epoch": time.time(),
        "base_url": BASE_URL,
        "query": args.query,
        "category_roots": CATEGORY_ROOTS,
        "pages": [],
        "summary": [],
        "source_file": inspect_source_file(args.scraper),
    }

    session = requests.Session()

    print("=" * 88)
    print("DELOOX DISCOVERY DIAGNOSTIC V3")
    print(f"QUERY: {args.query}")
    print(f"BASE:  {BASE_URL}")
    print("=" * 88)

    for index, root in enumerate(CATEGORY_ROOTS, 1):
        print(f"\n[{index}/{len(CATEGORY_ROOTS)}] GET {root}", flush=True)

        page = fetch(session, root, args.timeout)

        # The helper intentionally performs the production import comparison.
        # If the caller asks to suppress it, remove that section after analysis.
        if args.no_production_import:
            # We still need all raw evidence, so temporarily compare with a
            # minimal report that does not import production code.
            raw = page.get("raw_html", "")
            if raw:
                page_analysis = {
                    "request": {k: v for k, v in page.items() if k != "raw_html"},
                    "query": args.query,
                    "query_tokens": sorted(tokens(args.query)),
                    "query_found_case_insensitive": clean(args.query).casefold() in raw.casefold(),
                    "query_occurrences": find_occurrences(raw, args.query, 30),
                    "regex": extract_urls_by_regex(raw, args.query),
                    "dom": inspect_dom(raw, args.query),
                    "json_js": inspect_json_js(raw, args.query),
                    "production_scraper": {"disabled": True},
                }
            else:
                page_analysis = {
                    "request": {k: v for k, v in page.items() if k != "raw_html"},
                    "analysis_skipped": True,
                }
        else:
            page_analysis = analyze_page(page, args.query)

        report["pages"].append(page_analysis)

        req = page_analysis.get("request", {})
        print(
            f"status={req.get('status')} "
            f"bytes={req.get('bytes_text')} "
            f"elapsed={req.get('elapsed_seconds')}s",
            flush=True,
        )

        if page_analysis.get("analysis_skipped"):
            print("No HTML body available.", flush=True)
            continue

        print(
            "query="
            + str(page_analysis.get("query_found_case_insensitive"))
            + " | "
            + f"category_urls={page_analysis.get('cross_check', {}).get('unique_category_urls_seen_anywhere', [])[:3]}"
            + " | "
            + f"product_urls={page_analysis.get('cross_check', {}).get('unique_product_urls_seen_anywhere', [])[:3]}",
            flush=True,
        )

        prod = page_analysis.get("production_scraper", {})
        if prod.get("imported"):
            c = prod.get("candidate_product_urls")
            l = prod.get("category_product_line_links")
            print(
                "production:"
                f" candidate={c.get('count') if isinstance(c, dict) else c}"
                f" line_links={l.get('count') if isinstance(l, dict) else l}",
                flush=True,
            )

    report["summary"] = build_summary(report)

    print("\n" + "=" * 88)
    print("CONCLUSION")
    print("=" * 88)
    for item in report["summary"]:
        print("- " + item)

    output = Path(args.output)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\nFULL REPORT: {output.resolve()}")
    print("=" * 88)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
    
