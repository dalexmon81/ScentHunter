"""Deloox generic category-structure diagnostic.

This is a diagnostic only. It contains no perfume, brand, SKU or product URL
exceptions. It downloads one generic Deloox category and reports the actual
HTML/JSON structure needed by the generic discovery layer.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.deloox.com"
DEFAULT_CATEGORY = BASE_URL + "/category/1000003/fragrances.html"
TIMEOUT = 10
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "en-GB,en;q=0.9",
}


def clean(v):
    return re.sub(r"\s+", " ", str(v or "")).strip()


def tokens(v):
    return {x for x in re.sub(r"[^a-z0-9]+", " ", clean(v).lower()).split() if len(x) > 1}


def absolute(raw):
    raw = clean(raw).replace("\\/", "/")
    if not raw:
        return ""
    return urljoin(BASE_URL, raw).split("#")[0].split("?")[0]


def extract_category_links(html):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(raw, label="", source="html"):
        u = absolute(raw)
        if not u:
            return
        p = urlparse(u)
        if p.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
            return
        if "/category/" not in p.path.lower():
            return
        if u in seen:
            return
        seen.add(u)
        found.append({"url": u, "label": clean(label), "source": source})

    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/category/" in href.lower():
            add(href, a.get_text(" ", strip=True), "anchor")

    raw = html.replace("\\\\/", "/")
    patterns = (
        r'https?://(?:www\.)?deloox\.com(?:/en|/it|/nl)?/category/\d+/[^"\'<>\s]+\.html',
        r'(?<![A-Za-z0-9])(?:/(?:en|it|nl)/)?category/\d+/[^"\'<>\s]+\.html',
    )
    for pat in patterns:
        for m in re.finditer(pat, raw, re.I):
            add(m.group(0), "", "raw_regex")

    return found


def extract_product_urls(html):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(raw, source):
        u = absolute(raw)
        if not u:
            return
        p = urlparse(u)
        if p.netloc.lower() not in {"deloox.com", "www.deloox.com"}:
            return
        if "/product/" not in p.path.lower() or u in seen:
            return
        seen.add(u)
        found.append({"url": u, "source": source})

    for a in soup.find_all("a", href=True):
        if "/product/" in a.get("href", "").lower():
            add(a.get("href"), "anchor")

    raw = html.replace("\\\\/", "/")
    pats = (
        r'https?://(?:www\.)?deloox\.com[^"\'<>\s]*/product/[^"\'<>\s]+',
        r'(?<![A-Za-z0-9])(?:/|(?:en|it|nl)/)product/[^"\'<>\s]+',
    )
    for pat in pats:
        for m in re.finditer(pat, raw, re.I):
            add(m.group(0), "raw_regex")

    return found


def inspect_scripts(html):
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script")
    result = {
        "script_count": len(scripts),
        "jsonld_count": 0,
        "scripts_with_category": [],
        "scripts_with_product": [],
        "scripts_with_product_line_terms": [],
        "script_type_counts": dict(Counter(clean(s.get("type")) or "<none>" for s in scripts)),
    }

    for i, s in enumerate(scripts):
        text = s.get_text("", strip=False) or ""
        typ = clean(s.get("type"))
        if typ.lower() == "application/ld+json":
            result["jsonld_count"] += 1
        if "/category/" in text.lower():
            result["scripts_with_category"].append({"index": i, "type": typ, "chars": len(text), "sample": clean(text)[:500]})
        if "/product/" in text.lower():
            result["scripts_with_product"].append({"index": i, "type": typ, "chars": len(text), "sample": clean(text)[:500]})
        if re.search(r"product.?line|productLine|product_line", text, re.I):
            result["scripts_with_product_line_terms"].append({"index": i, "type": typ, "chars": len(text), "sample": clean(text)[:500]})

    # Keep output bounded while preserving enough evidence to identify the structure.
    for k in ("scripts_with_category", "scripts_with_product", "scripts_with_product_line_terms"):
        result[k] = result[k][:20]
    return result


def diagnose(url):
    out = {
        "requested_url": url,
        "request": {},
        "html": {},
        "category_links": [],
        "product_urls": [],
        "scripts": {},
        "signals": {},
        "error": None,
    }

    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        out["request"] = {
            "status": r.status_code,
            "final_url": r.url,
            "content_type": r.headers.get("content-type", ""),
            "content_length_header": r.headers.get("content-length"),
        }
    except requests.RequestException as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out

    html = r.text or ""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""

    out["html"] = {
        "bytes": len(html.encode("utf-8", errors="ignore")),
        "chars": len(html),
        "title": clean(title),
        "has_html": bool(soup.find("html")),
        "has_body": bool(soup.body),
    }
    out["category_links"] = extract_category_links(html)
    out["product_urls"] = extract_product_urls(html)
    out["scripts"] = inspect_scripts(html)

    low = html.lower()
    out["signals"] = {
        "category_occurrences": low.count("/category/"),
        "product_occurrences": low.count("/product/"),
        "product_line_occurrences": len(re.findall(r"product.?line|productLine|product_line", html, re.I)),
        "jsonld_occurrences": low.count("application/ld+json"),
        "next_data": "__next_data__" in low,
        "next_flight": "self.__next_f.push" in low or "self.__next_f" in low,
        "nuxt": "__nuxt" in low,
        "apollo": "apollo" in low,
    }

    # Show the most useful category/product URL samples, but do not dump the page.
    out["category_links"] = out["category_links"][:50]
    out["product_urls"] = out["product_urls"][:50]
    return out


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CATEGORY
    print(json.dumps(diagnose(url), ensure_ascii=False, indent=2))
