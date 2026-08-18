import argparse
import hashlib
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


# ============================================================
# SABINA — DIAGNOSTIC DEFINITIVO
# ============================================================
#
# Questo file NON è uno scraper di produzione.
# Serve esclusivamente a stabilire, in una sola esecuzione,
# DOVE Sabina rende disponibile (o nasconde) un prodotto:
#
#   1) homepage / sessione
#   2) robots.txt
#   3) sitemap index
#   4) sitemap figli
#   5) ricerca moderna
#   6) ricerca controller
#   7) ricerca legacy
#   8) eventuali URL alternativi di ricerca
#   9) HTML / JSON / JSON-LD / script
#  10) redirect, cookie, header, challenge
#  11) URL prodotto trovati
#  12) verifica diretta delle URL prodotto candidate
#
# Nessun prodotto, marca, SKU o URL prodotto è hard-coded.
# La query arriva da riga di comando.
#
# Esempio:
#   python sabina_DIAGNOSTIC_DEFINITIVO.py "Liquid Brun"
#
# Il report completo viene scritto in:
#   sabina_diagnostic_definitivo/
#
# ============================================================


STORE = "Sabina"
BASE_URL = "https://www.sabina.com"
TIMEOUT = 30
RUN_ID = time.strftime("%Y%m%d_%H%M%S")
OUT = Path(f"sabina_diagnostic_definitivo/{RUN_ID}")
OUT.mkdir(parents=True, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8,it;q=0.7",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": BASE_URL + "/es/",
}

PRODUCT_PATH_RE = re.compile(
    r"^/(?:es|it|fr|en|de|nl)/.+/(\d+)-[^/]+\.html$",
    re.I,
)

CHALLENGE_WORDS = (
    "captcha",
    "cloudflare",
    "attention required",
    "verify you are human",
    "cf-chl",
    "challenge-platform",
    "access denied",
    "forbidden",
    "robot check",
    "security check",
    "ddos",
    "akamai",
    "perimeterx",
    "incapsula",
    "datadome",
)

SEARCH_ENDPOINTS = (
    ("modern_s", "/es/buscar?s={q}"),
    ("modern_controller", "/es/buscar?controller=search&s={q}"),
    ("legacy_s", "/es/buscar_old?s={q}"),
    ("legacy_controller", "/es/buscar_old?controller=search&s={q}"),
    ("search_query", "/es/buscar?search_query={q}"),
    ("search_query_legacy", "/es/buscar_old?search_query={q}"),
)

ROBOTS_URL = BASE_URL + "/robots.txt"
SITEMAP_INDEX_CANDIDATES = (
    BASE_URL + "/sitemap_index_shop_1.xml",
    BASE_URL + "/sitemap_index.xml",
    BASE_URL + "/sitemap.xml",
)


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def norm(value):
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = value.lower()
    value = re.sub(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)", " ", value)
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def query_tokens(query):
    ignored = {
        "eau", "de", "parfum", "perfume", "edp", "edt",
        "extrait", "spray", "for", "by", "ml", "pour",
    }
    return [
        token for token in norm(query).split()
        if token not in ignored
    ]


def query_in_text(text, query):
    tokens = query_tokens(query)
    value = norm(text)
    return bool(tokens) and all(token in value for token in tokens)


def is_product_url(url):
    return bool(PRODUCT_PATH_RE.match(urlparse(url).path))


def sha256(text):
    return hashlib.sha256(
        text.encode("utf-8", errors="replace")
    ).hexdigest()


def save_text(name, text):
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(str(text or ""), encoding="utf-8")
    return str(target)


def save_json(name, data):
    target = OUT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return str(target)


def response_meta(response, requested_url):
    html = response.text or ""
    low = html.lower()

    challenge_hits = [
        word for word in CHALLENGE_WORDS
        if word in low
    ]

    return {
        "requested_url": requested_url,
        "final_url": response.url,
        "status": response.status_code,
        "reason": response.reason,
        "content_type": response.headers.get("content-type"),
        "content_length_header": response.headers.get("content-length"),
        "server": response.headers.get("server"),
        "via": response.headers.get("via"),
        "cf_ray": response.headers.get("cf-ray"),
        "x_cache": response.headers.get("x-cache"),
        "location": response.headers.get("location"),
        "elapsed_seconds": None,
        "html_length": len(html),
        "sha256": sha256(html),
        "challenge_hits": challenge_hits,
        "cookies": {},
        "query_occurrences": {},
        "product_url_count": 0,
        "product_urls": [],
        "contains_jsonld": False,
        "contains_product_jsonld": False,
        "contains_search_results_word": False,
        "contains_liquid_like_query": False,
    }


def extract_urls_from_html(html, base_url):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(raw):
        if not raw:
            return
        absolute = urljoin(base_url, str(raw)).split("#")[0]
        if absolute.startswith("http") and absolute not in seen:
            seen.add(absolute)
            found.append(absolute)

    for anchor in soup.find_all("a", href=True):
        add(anchor.get("href"))
        add(anchor.get("data-href"))
        add(anchor.get("data-product-url"))
        add(anchor.get("data-url"))

    for tag in soup.find_all(True):
        for attr in (
            "href",
            "data-href",
            "data-product-url",
            "data-url",
            "data-link",
            "data-product-link",
        ):
            if tag.has_attr(attr):
                add(tag.get(attr))

    # URLs embedded directly in scripts / JSON.
    for match in re.findall(
        r'https?://[^"\'<>\s\\]+',
        html,
        flags=re.I,
    ):
        add(match)

    return found


def inspect_html(html, base_url, query):
    soup = BeautifulSoup(html, "html.parser")
    raw_urls = extract_urls_from_html(html, base_url)

    product_urls = [
        url for url in raw_urls
        if is_product_url(url)
    ]

    text = soup.get_text(" ", strip=True)
    normalized_html = norm(html)
    normalized_text = norm(text)

    jsonld_scripts = soup.select(
        'script[type="application/ld+json"]'
    )

    product_jsonld = 0
    jsonld_examples = []

    for script in jsonld_scripts:
        raw = script.string or script.get_text()
        if not raw:
            continue

        if len(jsonld_examples) < 5:
            jsonld_examples.append(raw[:3000])

        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = data if isinstance(data, list) else [data]

        while stack:
            item = stack.pop()

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            if item.get("@graph"):
                stack.extend(item["@graph"])

            item_type = item.get("@type")
            types = (
                item_type
                if isinstance(item_type, list)
                else [item_type]
            )

            if any(
                str(t).lower() == "product"
                for t in types
            ):
                product_jsonld += 1

    query_variants = {
        "raw": str(query),
        "normalized": norm(query),
        "plus": quote_plus(query),
    }

    occurrences = {}
    for name, value in query_variants.items():
        occurrences[name] = {
            "raw_html": html.lower().count(value.lower()),
            "normalized_html": normalized_html.count(norm(value)),
            "visible_text": normalized_text.count(norm(value)),
        }

    query_token_hits = {}
    for token in query_tokens(query):
        query_token_hits[token] = {
            "html": normalized_html.count(token),
            "visible_text": normalized_text.count(token),
            "product_urls": sum(
                token in norm(url)
                for url in product_urls
            ),
        }

    return {
        "anchor_and_embedded_url_count": len(raw_urls),
        "product_url_count": len(product_urls),
        "product_urls": product_urls[:200],
        "query_occurrences": occurrences,
        "query_token_hits": query_token_hits,
        "contains_search_results_word": (
            "search results" in normalized_html
            or "resultados de busqueda" in normalized_html
            or "resultados de búsqueda" in normalized_html
            or "resultats de recherche" in normalized_html
        ),
        "contains_query_in_visible_text": query_in_text(
            text, query
        ),
        "contains_query_in_html": query_in_text(
            html, query
        ),
        "contains_jsonld": bool(jsonld_scripts),
        "jsonld_count": len(jsonld_scripts),
        "contains_product_jsonld": product_jsonld > 0,
        "product_jsonld_count": product_jsonld,
        "jsonld_examples": jsonld_examples,
    }


def fetch(session, label, url, query):
    started = time.time()

    record = {
        "label": label,
        "requested_url": url,
        "error": None,
    }

    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        elapsed = round(time.time() - started, 3)

        meta = response_meta(response, url)
        meta["elapsed_seconds"] = elapsed
        meta["cookies"] = session.cookies.get_dict()

        if "text" in str(
            response.headers.get("content-type", "")
        ).lower() or response.text:
            inspection = inspect_html(
                response.text,
                response.url,
                query,
            )
            meta.update(inspection)

            save_text(
                f"raw/{label}.html",
                response.text,
            )

        save_json(
            f"meta/{label}.json",
            meta,
        )

        record.update(meta)

        return record

    except Exception as exc:
        record["error"] = repr(exc)
        save_json(
            f"meta/{label}.json",
            record,
        )
        return record


def discover_sitemap_urls(session, sitemap_url, query):
    result = {
        "requested_url": sitemap_url,
        "status": None,
        "final_url": None,
        "error": None,
        "sitemap_children": [],
        "product_urls": [],
        "query_candidate_urls": [],
    }

    try:
        response = session.get(
            sitemap_url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        result["status"] = response.status_code
        result["final_url"] = response.url

        save_text(
            "sitemaps/" + re.sub(
                r"[^a-zA-Z0-9_.-]+",
                "_",
                sitemap_url.replace(BASE_URL, "").strip("/"),
            ) + ".xml",
            response.text,
        )

        if response.status_code >= 400:
            return result

        soup = BeautifulSoup(response.text, "xml")
        locs = [
            clean(loc.get_text())
            for loc in soup.find_all("loc")
            if clean(loc.get_text())
        ]

        # If this is a sitemap index, inspect its child sitemaps.
        child_sitemaps = [
            loc for loc in locs
            if loc.lower().endswith(".xml")
        ]

        result["sitemap_children"] = child_sitemaps

        all_product_urls = []

        # Direct product URLs can exist in a sitemap itself.
        for loc in locs:
            if is_product_url(loc):
                all_product_urls.append(loc)

        # Inspect every child sitemap in this diagnostic run.
        for index, child_url in enumerate(child_sitemaps):
            try:
                child = session.get(
                    child_url,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )

                child_name = re.sub(
                    r"[^a-zA-Z0-9_.-]+",
                    "_",
                    child_url.replace(BASE_URL, "").strip("/"),
                )

                save_text(
                    f"sitemaps/child_{index:03d}_{child_name}.xml",
                    child.text,
                )

                if child.status_code >= 400:
                    continue

                child_soup = BeautifulSoup(
                    child.text,
                    "xml",
                )

                for child_loc in child_soup.find_all("loc"):
                    value = clean(child_loc.get_text())

                    if is_product_url(value):
                        all_product_urls.append(value)

            except Exception:
                continue

        # Deduplicate.
        deduped = []
        seen = set()

        for url in all_product_urls:
            if url not in seen:
                seen.add(url)
                deduped.append(url)

        result["product_urls"] = deduped

        tokens = query_tokens(query)

        result["query_candidate_urls"] = [
            url for url in deduped
            if all(
                token in norm(urlparse(url).path)
                for token in tokens
            )
        ]

        return result

    except Exception as exc:
        result["error"] = repr(exc)
        return result


def verify_product_candidate(
    session,
    url,
    query,
    index,
):
    label = f"product_candidate_{index:03d}"

    record = fetch(
        session,
        label,
        url,
        query,
    )

    record["query_matches_final_url"] = query_in_text(
        record.get("final_url", ""),
        query,
    )

    record["query_matches_product_urls"] = any(
        query_in_text(candidate, query)
        for candidate in record.get(
            "product_urls",
            [],
        )
    )

    return record


def build_conclusion(report):
    sections = report["sections"]

    search_sections = [
        value for key, value in sections.items()
        if key.startswith("search_")
    ]

    total_search_product_urls = sum(
        int(item.get("product_url_count", 0) or 0)
        for item in search_sections
    )

    sitemap_candidates = len(
        report["sitemap"].get(
            "query_candidate_urls",
            [],
        )
    )

    verified = report["verified_product_candidates"]

    verified_success = [
        item for item in verified
        if item.get("status") == 200
        and not item.get("error")
    ]

    verified_matching = [
        item for item in verified_success
        if (
            item.get("query_matches_final_url")
            or item.get("contains_query_in_html")
            or item.get("contains_query_in_visible_text")
        )
    ]

    challenge_hits = sorted({
        hit
        for section in sections.values()
        for hit in section.get(
            "challenge_hits",
            [],
        )
    })

    conclusion = {
        "search_product_urls_total": total_search_product_urls,
        "sitemap_query_candidates": sitemap_candidates,
        "verified_candidates": len(verified),
        "verified_http_200": len(verified_success),
        "verified_matching_candidates": len(verified_matching),
        "challenge_hits": challenge_hits,
        "diagnosis": None,
    }

    if verified_matching:
        conclusion["diagnosis"] = (
            "PRODUCT_URL_DIRECTLY_REACHABLE: "
            "Sabina exposes at least one matching product candidate "
            "and the product page is reachable. The problem is therefore "
            "not basic HTTP reachability; inspect discovery/parsing "
            "and ScentHunter validation separately."
        )
    elif sitemap_candidates and not verified_matching:
        conclusion["diagnosis"] = (
            "SITEMAP_DISCOVERY_ONLY: "
            "the product URL pattern is discoverable through sitemap data "
            "but candidate product pages could not be validated as matching."
        )
    elif total_search_product_urls:
        conclusion["diagnosis"] = (
            "SEARCH_DISCOVERY_EXPOSES_PRODUCT_URLS: "
            "Sabina search responses expose product URLs, but no verified "
            "matching product page was obtained in the diagnostic."
        )
    elif challenge_hits:
        conclusion["diagnosis"] = (
            "HTTP_CHALLENGE_OR_ACCESS_CONTROL: "
            "the responses contain challenge/access-control indicators. "
            "The scraper cannot be diagnosed as a normal search/parser "
            "problem until this is accounted for."
        )
    else:
        conclusion["diagnosis"] = (
            "NO_PRODUCT_URL_EXPOSED_TO_HTTP_CLIENT: "
            "none of the tested search endpoints or sitemap paths exposed "
            "a matching product URL to this HTTP client. This strongly "
            "points to Sabina's server-side/browser-side discovery behavior "
            "rather than the final product parser."
        )

    return conclusion


def main():
    parser = argparse.ArgumentParser(
        description="Definitive generic Sabina HTTP/discovery diagnostic"
    )
    parser.add_argument(
        "query",
        nargs="?",
        default="Liquid Brun",
        help="Query to diagnose",
    )

    args = parser.parse_args()
    query = clean(args.query)

    session = requests.Session()
    session.headers.update(HEADERS)

    report = {
        "diagnostic_version": "sabina-DEFINITIVE-2026-08-18-1",
        "store": STORE,
        "query": query,
        "started_at": time.strftime(
            "%Y-%m-%dT%H:%M:%S%z"
        ),
        "output_directory": str(OUT),
        "sections": {},
        "sitemap": {},
        "verified_product_candidates": [],
    }

    print("=" * 72)
    print("SCENTHUNTER — SABINA DEFINITIVE DIAGNOSTIC")
    print("=" * 72)
    print(f"QUERY: {query}")
    print(f"OUTPUT: {OUT.resolve()}")
    print()

    # --------------------------------------------------------
    # 1. Establish first-party session.
    # --------------------------------------------------------
    print("[1/4] BOOTSTRAP SESSION")

    bootstrap = fetch(
        session,
        "bootstrap_homepage",
        BASE_URL + "/es/",
        query,
    )
    report["sections"]["bootstrap_homepage"] = bootstrap

    print(
        f"  status={bootstrap.get('status')} "
        f"final={bootstrap.get('final_url')} "
        f"bytes={bootstrap.get('html_length')} "
        f"cookies={bootstrap.get('cookies')}"
    )

    # --------------------------------------------------------
    # 2. robots + sitemap.
    # --------------------------------------------------------
    print()
    print("[2/4] ROBOTS / SITEMAPS")

    robots = fetch(
        session,
        "robots",
        ROBOTS_URL,
        query,
    )
    report["sections"]["robots"] = robots

    sitemap = {
        "tested_candidates": [],
        "selected_index": None,
        "sitemap_children": [],
        "product_urls": [],
        "query_candidate_urls": [],
        "error": None,
    }

    for index, candidate in enumerate(
        SITEMAP_INDEX_CANDIDATES
    ):
        result = discover_sitemap_urls(
            session,
            candidate,
            query,
        )

        sitemap["tested_candidates"].append(result)

        print(
            f"  sitemap[{index}] "
            f"status={result.get('status')} "
            f"children={len(result.get('sitemap_children', []))} "
            f"products={len(result.get('product_urls', []))} "
            f"query_candidates={len(result.get('query_candidate_urls', []))}"
        )

        if (
            result.get("status") == 200
            and (
                result.get("product_urls")
                or result.get("sitemap_children")
            )
            and sitemap["selected_index"] is None
        ):
            sitemap["selected_index"] = index
            sitemap["sitemap_children"] = result.get(
                "sitemap_children",
                [],
            )
            sitemap["product_urls"] = result.get(
                "product_urls",
                [],
            )
            sitemap["query_candidate_urls"] = result.get(
                "query_candidate_urls",
                [],
            )

    report["sitemap"] = sitemap

    # --------------------------------------------------------
    # 3. Every search endpoint in one run.
    # --------------------------------------------------------
    print()
    print("[3/4] SEARCH ENDPOINT MATRIX")

    for label, path_template in SEARCH_ENDPOINTS:
        url = BASE_URL + path_template.format(
            q=quote_plus(query)
        )

        result = fetch(
            session,
            "search_" + label,
            url,
            query,
        )

        report["sections"]["search_" + label] = result

        print(
            f"  {label:<24} "
            f"status={result.get('status')} "
            f"bytes={result.get('html_length')} "
            f"products={result.get('product_url_count')} "
            f"query_visible={result.get('contains_query_in_visible_text')} "
            f"query_html={result.get('contains_query_in_html')} "
            f"challenge={result.get('challenge_hits')}"
        )

    # --------------------------------------------------------
    # 4. Verify every unique matching sitemap/search candidate.
    # --------------------------------------------------------
    print()
    print("[4/4] DIRECT PRODUCT VALIDATION")

    candidate_urls = []
    seen = set()

    # Sitemap candidates first.
    for url in sitemap.get(
        "query_candidate_urls",
        [],
    ):
        if url not in seen:
            seen.add(url)
            candidate_urls.append(url)

    # Then search candidates.
    for section in report["sections"].values():
        for url in section.get(
            "product_urls",
            [],
        ):
            if not query_in_text(url, query):
                continue
            if url not in seen:
                seen.add(url)
                candidate_urls.append(url)

    print(
        f"  unique matching candidates={len(candidate_urls)}"
    )

    # Validate all candidates, not just the first one.
    for index, url in enumerate(candidate_urls):
        print(
            f"  validating {index + 1}/{len(candidate_urls)}: "
            f"{url}"
        )

        result = verify_product_candidate(
            session,
            url,
            query,
            index,
        )

        report["verified_product_candidates"].append(
            result
        )

    report["conclusion"] = build_conclusion(report)

    save_json(
        "report.json",
        report,
    )

    # Human-readable final report.
    lines = [
        "=" * 72,
        "SCENTHUNTER — SABINA DEFINITIVE DIAGNOSTIC REPORT",
        "=" * 72,
        f"QUERY: {query}",
        "",
        "SEARCH MATRIX:",
    ]

    for label, result in report["sections"].items():
        if not label.startswith("search_"):
            continue

        lines.append(
            f"- {label}: "
            f"status={result.get('status')} "
            f"final={result.get('final_url')} "
            f"bytes={result.get('html_length')} "
            f"product_urls={result.get('product_url_count')} "
            f"query_visible={result.get('contains_query_in_visible_text')} "
            f"query_html={result.get('contains_query_in_html')} "
            f"jsonld_product={result.get('contains_product_jsonld')} "
            f"challenge={result.get('challenge_hits')}"
        )

    lines.extend([
        "",
        "SITEMAP:",
        f"- selected_index={sitemap.get('selected_index')}",
        f"- children={len(sitemap.get('sitemap_children', []))}",
        f"- product_urls={len(sitemap.get('product_urls', []))}",
        f"- query_candidates={len(sitemap.get('query_candidate_urls', []))}",
        "",
        "DIRECT PRODUCT VALIDATION:",
    ])

    for item in report["verified_product_candidates"]:
        lines.append(
            f"- {item.get('requested_url')}: "
            f"status={item.get('status')} "
            f"final={item.get('final_url')} "
            f"query_final={item.get('query_matches_final_url')} "
            f"query_html={item.get('contains_query_in_html')} "
            f"query_text={item.get('contains_query_in_visible_text')} "
            f"challenge={item.get('challenge_hits')}"
        )

    conclusion = report["conclusion"]

    lines.extend([
        "",
        "CONCLUSION:",
        f"- search_product_urls_total="
        f"{conclusion['search_product_urls_total']}",
        f"- sitemap_query_candidates="
        f"{conclusion['sitemap_query_candidates']}",
        f"- verified_candidates="
        f"{conclusion['verified_candidates']}",
        f"- verified_http_200="
        f"{conclusion['verified_http_200']}",
        f"- verified_matching_candidates="
        f"{conclusion['verified_matching_candidates']}",
        f"- challenge_hits="
        f"{conclusion['challenge_hits']}",
        "",
        conclusion["diagnosis"],
        "",
        f"FULL REPORT: {(OUT / 'report.json').resolve()}",
        f"RAW FILES: {(OUT / 'raw').resolve()}",
        f"METADATA: {(OUT / 'meta').resolve()}",
        f"SITEMAPS: {(OUT / 'sitemaps').resolve()}",
    ])

    final_text = "\n".join(lines)

    save_text(
        "sabina_diagnostic_definitivo.txt",
        final_text,
    )

    print()
    print(final_text)


if __name__ == "__main__":
    main()
