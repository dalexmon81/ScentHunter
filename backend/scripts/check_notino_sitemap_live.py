#!/usr/bin/env python3
"""One-shot, read-only diagnostic for Notino.fr's published sitemap.

This probe makes at most one HTTP request. It does not retry, use a proxy,
invoke a browser, fetch product pages, access credentials, or touch any database.
A reachable sitemap is only discovery evidence; it does not verify prices/offers.
"""
from __future__ import annotations

import json
import re
import sys
from urllib.parse import urlparse
from xml.etree import ElementTree

import requests

from scrapers.notino import scraper

ALLOWED_HOSTS = {"notino.fr", "www.notino.fr"}
PRODUCT_PATH = re.compile(r"/p-\d+(?:/|$)", re.I)


def main() -> int:
    report = {
        "mode": "one_request_public_sitemap_diagnostic",
        "url": scraper.SITEMAP_URL,
        "http_status": None,
        "redirect_host": None,
        "sitemap_type": None,
        "sitemap_entries": 0,
        "product_url_count": 0,
        "child_sitemap_count": 0,
        "product_url_samples": [],
        "child_sitemap_samples": [],
        "database_accessed": False,
        "catalog_written": False,
        "queue_touched": False,
        "product_pages_fetched": 0,
    }
    session = scraper._new_session()
    try:
        response = session.get(
            scraper.SITEMAP_URL,
            timeout=(8, 15),
            allow_redirects=True,
        )
        report["http_status"] = response.status_code
        parsed_final = urlparse(response.url)
        report["redirect_host"] = (parsed_final.hostname or "").lower()

        if report["redirect_host"] not in ALLOWED_HOSTS:
            report["status"] = "BLOCKED_UNEXPECTED_REDIRECT"
        elif response.status_code in {403, 429}:
            report["status"] = "BLOCKED"
        elif response.status_code != 200:
            report["status"] = "HTTP_ERROR"
        else:
            try:
                root = ElementTree.fromstring(response.content)
            except ElementTree.ParseError as exc:
                report["status"] = "INVALID_XML"
                report["error"] = type(exc).__name__
            else:
                tag = root.tag.rsplit("}", 1)[-1].lower()
                locs = [
                    (node.text or "").strip()
                    for node in root.iter()
                    if node.tag.rsplit("}", 1)[-1].lower() == "loc"
                    and (node.text or "").strip()
                ]
                report["sitemap_type"] = tag
                report["sitemap_entries"] = len(locs)
                product_urls = [
                    url for url in locs
                    if urlparse(url).hostname in ALLOWED_HOSTS
                    and PRODUCT_PATH.search(urlparse(url).path or "")
                ]
                child_sitemaps = [
                    url for url in locs
                    if urlparse(url).hostname in ALLOWED_HOSTS
                    and not PRODUCT_PATH.search(urlparse(url).path or "")
                ]
                report["product_url_count"] = len(product_urls)
                report["child_sitemap_count"] = len(child_sitemaps)
                report["product_url_samples"] = product_urls[:8]
                report["child_sitemap_samples"] = child_sitemaps[:8]
                if product_urls:
                    report["status"] = "PRODUCT_URLS_FOUND"
                elif tag == "sitemapindex" and child_sitemaps:
                    report["status"] = "INDEX_REACHABLE_CHILD_SITEMAPS_NOT_FETCHED"
                else:
                    report["status"] = "REACHABLE_NO_PRODUCT_URLS"
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        report["http_status"] = status
        report["status"] = "BLOCKED" if status in {403, 429} else "REQUEST_ERROR"
        report["error"] = type(exc).__name__
    finally:
        session.close()

    print("NOTINO_SITEMAP_PROBE=" + json.dumps(report, ensure_ascii=False), flush=True)
    # Diagnostic-only: the marker, not the CI exit code, carries the outcome.
    return 0


if __name__ == "__main__":
    sys.exit(main())
