from __future__ import annotations

import html as htmllib
import json
import re
import time
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query

app = FastAPI(title="ScentHunter Deloox Diagnostic")

BASE_URL = "https://www.deloox.be"
TIMEOUT = 15
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

ROOTS = (
    BASE_URL + "/categorie/1075732/parfum-homme.html",
    BASE_URL + "/categorie/1000063/parfum-femme.html",
    BASE_URL + "/categorie/1075918/parfum-mixte.html",
)


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def norm(v):
    return re.sub(
        r"\s+",
        " ",
        re.sub(r"[^a-z0-9]+", " ", clean(v).lower()),
    ).strip()


def tokens(v):
    return {x for x in norm(v).split() if len(x) > 1}


def query_match(text, query):
    q = tokens(query)
    return bool(q) and q.issubset(tokens(text))


def decode_text(value):
    value = str(value or "")
    for _ in range(4):
        value = (
            value.replace("\\/", "/")
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\u0026", "&")
            .replace("\\u003F", "?")
            .replace("\\u003f", "?")
        )
    return htmllib.unescape(value)


def safe_url(raw):
    raw = decode_text(raw).strip()
    if not raw:
        return None
    url = urljoin(BASE_URL, raw).split("#")[0].split("?")[0]
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.netloc.lower() not in {"deloox.be", "www.deloox.be"}:
        return None
    return url


def extract_urls(text, pattern):
    found = []
    seen = set()
    for raw in re.findall(pattern, text or "", re.I):
        url = safe_url(raw)
        if url and url not in seen:
            seen.add(url)
            found.append(url)
    return found


def fetch(session, url, stage, diagnostics):
    started = time.perf_counter()
    record = {
        "stage": stage,
        "url": url,
    }
    try:
        response = session.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        elapsed = round(time.perf_counter() - started, 3)
        record.update(
            {
                "status": response.status_code,
                "final_url": response.url,
                "bytes": len(response.content or b""),
                "elapsed_s": elapsed,
                "content_type": response.headers.get("content-type"),
            }
        )
        diagnostics["requests"].append(record)
        return response
    except Exception as exc:
        elapsed = round(time.perf_counter() - started, 3)
        record.update(
            {
                "error": repr(exc),
                "elapsed_s": elapsed,
            }
        )
        diagnostics["requests"].append(record)
        return None


def inspect_document(html, query):
    soup = BeautifulSoup(html or "", "html.parser")
    raw = decode_text(html or "")
    rendered = soup.get_text(" ", strip=True)

    category_pattern = (
        r'(?:https?://(?:www\.)?deloox\.be)?'
        r'/(?:en/|fr/|nl/|it/)?'
        r'(?:categorie|category|categoria)/\d+/[^"\'<>\s]+?\.html'
    )
    product_pattern = (
        r'(?:https?://(?:www\.)?deloox\.be)?'
        r'/(?:en/|fr/|nl/|it/)?'
        r'(?:produit|product)/\d+/[^"\'<>\s]+'
    )

    category_urls = extract_urls(raw, category_pattern)
    product_urls = extract_urls(raw, product_pattern)

    anchors = []
    query_anchor_matches = []
    query_attr_matches = []
    query_json_matches = []

    for a in soup.find_all("a", href=True):
        href = decode_text(a.get("href"))
        label = clean(a.get_text(" ", strip=True))
        item = {"href": href, "label": label}
        anchors.append(item)
        if query_match(f"{href} {label}", query):
            query_anchor_matches.append(item)

    for tag in soup.find_all(True):
        for attr_name, value in tag.attrs.items():
            values = value if isinstance(value, (list, tuple)) else [value]
            for value_item in values:
                if not isinstance(value_item, str):
                    continue
                value_decoded = decode_text(value_item)
                if query_match(f"{attr_name} {value_decoded}", query):
                    query_attr_matches.append(
                        {
                            "tag": tag.name,
                            "attribute": attr_name,
                            "value": value_decoded[:1000],
                        }
                    )

    q_lower = clean(query).lower()
    for script in soup.find_all("script"):
        script_text = script.get_text(" ", strip=True)
        if q_lower in script_text.lower() or norm(query) in norm(script_text):
            query_json_matches.append(
                {
                    "type": script.get("type"),
                    "bytes": len(script_text.encode("utf-8")),
                    "sample": script_text[:1500],
                }
            )

    raw_lower = raw.lower()
    rendered_lower = rendered.lower()

    return {
        "html_bytes": len((html or "").encode("utf-8")),
        "anchor_count": len(anchors),
        "category_url_count": len(category_urls),
        "category_urls": category_urls[:100],
        "product_url_count": len(product_urls),
        "product_urls": product_urls[:100],
        "category_path_counts": {
            "/categorie/": len(re.findall(r"/categorie/", raw, re.I)),
            "/category/": len(re.findall(r"/category/", raw, re.I)),
            "/categoria/": len(re.findall(r"/categoria/", raw, re.I)),
        },
        "product_path_counts": {
            "/produit/": len(re.findall(r"/produit/", raw, re.I)),
            "/product/": len(re.findall(r"/product/", raw, re.I)),
        },
        "query_occurrences": {
            "raw_html_case_insensitive": raw_lower.count(q_lower),
            "rendered_text_case_insensitive": rendered_lower.count(q_lower),
        },
        "query_anchor_matches": query_anchor_matches[:100],
        "query_attribute_matches": query_attr_matches[:100],
        "query_script_matches": query_json_matches[:20],
        "visible_query_contexts": _contexts(rendered, query),
    }


def _contexts(text, query, limit=10):
    result = []
    lower = text.lower()
    needle = clean(query).lower()
    if not needle:
        return result

    start = 0
    while len(result) < limit:
        pos = lower.find(needle, start)
        if pos < 0:
            break
        result.append(
            clean(text[max(0, pos - 500): pos + len(needle) + 500])
        )
        start = pos + max(1, len(needle))
    return result


def diagnose(query: str):
    query = clean(query)
    started_all = time.perf_counter()

    diagnostics = {
        "query": query,
        "base_url": BASE_URL,
        "timeout_s": TIMEOUT,
        "started_at_unix": time.time(),
        "stage": "start",
        "requests": [],
        "roots": list(ROOTS),
        "root_inspections": [],
        "summary": {},
    }

    if not query:
        diagnostics["stage"] = "error_empty_query"
        diagnostics["elapsed_total_s"] = round(
            time.perf_counter() - started_all, 3
        )
        return diagnostics

    session = requests.Session()

    try:
        diagnostics["stage"] = "session_created"

        for index, root in enumerate(ROOTS, 1):
            diagnostics["stage"] = f"root_{index}_before_fetch"

            response = fetch(
                session,
                root,
                f"root_{index}_fetch",
                diagnostics,
            )

            if response is None:
                diagnostics["stage"] = f"root_{index}_fetch_error"
                continue

            diagnostics["stage"] = f"root_{index}_after_fetch"

            if response.status_code >= 400:
                diagnostics["root_inspections"].append(
                    {
                        "root": root,
                        "status": response.status_code,
                        "skipped_inspection": True,
                    }
                )
                diagnostics["stage"] = f"root_{index}_http_error"
                continue

            diagnostics["stage"] = f"root_{index}_before_parse"

            try:
                inspection = inspect_document(response.text, query)
            except Exception as exc:
                diagnostics["root_inspections"].append(
                    {
                        "root": root,
                        "parse_error": repr(exc),
                    }
                )
                diagnostics["stage"] = f"root_{index}_parse_error"
                continue

            inspection["root"] = root
            diagnostics["root_inspections"].append(inspection)

            diagnostics["stage"] = f"root_{index}_after_parse"

            # Stop only for the diagnostic when a root actually contains
            # matching product/category evidence. This keeps the response
            # small while still showing the exact successful stage.
            if (
                inspection["product_url_count"]
                or inspection["query_anchor_matches"]
                or inspection["query_attribute_matches"]
                or inspection["query_script_matches"]
            ):
                diagnostics["stage"] = f"root_{index}_evidence_found"
                break

        diagnostics["stage"] = "summary"

        all_categories = []
        all_products = []
        for item in diagnostics["root_inspections"]:
            all_categories.extend(item.get("category_urls", []))
            all_products.extend(item.get("product_urls", []))

        diagnostics["summary"] = {
            "roots_checked": len(diagnostics["root_inspections"]),
            "requests_made": len(diagnostics["requests"]),
            "category_urls": list(dict.fromkeys(all_categories))[:100],
            "product_urls": list(dict.fromkeys(all_products))[:100],
            "category_urls_total": len(set(all_categories)),
            "product_urls_total": len(set(all_products)),
            "legacy_category_path_found": any(
                item.get("category_path_counts", {}).get("/category/", 0) > 0
                for item in diagnostics["root_inspections"]
            ),
            "legacy_product_path_found": any(
                item.get("product_path_counts", {}).get("/product/", 0) > 0
                for item in diagnostics["root_inspections"]
            ),
        }

        diagnostics["stage"] = "done"
        return diagnostics

    except Exception as exc:
        diagnostics["stage"] = "fatal_error"
        diagnostics["error"] = repr(exc)
        return diagnostics

    finally:
        session.close()
        diagnostics["elapsed_total_s"] = round(
            time.perf_counter() - started_all, 3
        )


@app.get("/diagnose-deloox")
def diagnose_deloox(
    q: str = Query(..., min_length=1, description="Perfume to diagnose")
):
    return diagnose(q)


@app.get("/")
def root():
    return {
        "service": "ScentHunter Deloox Diagnostic",
        "endpoint": "/diagnose-deloox?q=Liquid%20Brun",
        "base_url": BASE_URL,
    }
