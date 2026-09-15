from __future__ import annotations

import re
import traceback
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/deloox")
def debug_deloox(q: str = Query(..., min_length=2)):
    try:
        from scrapers.deloox.scraper import (
            BASE,
            HEADERS,
            TIMEOUT,
            discover,
            is_product_url,
            product_url,
            relevant,
        )

        query = str(q or "").strip()
        encoded = quote_plus(query)

        endpoints = (
            f"{BASE}/en/search?query={encoded}",
            f"{BASE}/en/search?q={encoded}",
            f"{BASE}/en/search?search={encoded}",
            f"https://www.deloox.nl/en/search?query={encoded}",
            f"https://www.deloox.es/en/search?query={encoded}",
        )

        session = requests.Session()
        pages = []

        try:
            for endpoint in endpoints:
                try:
                    r = session.get(
                        endpoint,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                        allow_redirects=True,
                    )

                    html = r.text or ""

                    page = {
                        "requested": endpoint,
                        "status_code": r.status_code,
                        "final_url": r.url,
                        "html_length": len(html),
                        "liquid_brun_hits": [],
                    }

                    # ANALYZE THE HTML EVEN WHEN HTTP STATUS IS 404.
                    soup = BeautifulSoup(
                        html,
                        "html.parser",
                    )

                    matching = []

                    for a in soup.find_all(
                        "a",
                        href=True,
                    ):
                        text = " ".join(
                            a.get_text(
                                " ",
                                strip=True,
                            ).split()
                        )

                        raw_href = str(
                            a.get("href") or ""
                        )

                        href = urljoin(
                            r.url,
                            raw_href,
                        )

                        blob = (
                            f"{text} {href}"
                        ).lower()

                        if not any(
                            term in blob
                            for term in (
                                "liquid",
                                "brun",
                                "limited",
                                "edition",
                            )
                        ):
                            continue

                        matching.append(
                            {
                                "text": text[:500],
                                "href": href[:1000],
                                "raw_href": raw_href[:1000],
                                "is_product_url": bool(
                                    is_product_url(href)
                                ),
                                "product_url": product_url(
                                    href
                                ),
                                "relevant_to_query": relevant(
                                    f"{text} {href}",
                                    query,
                                ),
                            }
                        )

                    page["liquid_brun_hits"] = matching[:200]

                    # Also inspect raw HTML around occurrences.
                    lower_html = html.lower()
                    snippets = []

                    for term in (
                        "liquid brun",
                        "limited edition",
                        "liquid-brun",
                        "liquid_brun",
                    ):
                        start = 0
                        count = 0

                        while count < 10:
                            pos = lower_html.find(
                                term,
                                start,
                            )

                            if pos < 0:
                                break

                            snippets.append(
                                {
                                    "term": term,
                                    "position": pos,
                                    "html": html[
                                        max(0, pos - 350):
                                        min(
                                            len(html),
                                            pos + 900,
                                        )
                                    ],
                                }
                            )

                            start = pos + len(term)
                            count += 1

                    page["raw_html_snippets"] = snippets

                    pages.append(page)

                except Exception as exc:
                    pages.append(
                        {
                            "requested": endpoint,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )

            # DIAGNOSTIC ONLY: inspect the Rasasi catalog used by the
            # actual Hawas discovery fix. This does not alter scraper
            # behavior; it only reports where candidate discovery stops.
            rasasi_endpoint = (
                f"{BASE}/it/categoria/"
                "1080044/rasasi-profumi.html"
            )

            try:
                r = session.get(
                    rasasi_endpoint,
                    headers=HEADERS,
                    timeout=TIMEOUT,
                    allow_redirects=True,
                )

                html = r.text or ""
                soup = BeautifulSoup(
                    html,
                    "html.parser",
                )

                product_links = []
                relevant_links = []
                priced_links = []
                seen_urls = set()

                for a in soup.find_all(
                    "a",
                    href=True,
                ):
                    raw_href = str(
                        a.get("href") or ""
                    )
                    href = urljoin(
                        r.url,
                        raw_href,
                    )

                    normalized_url = product_url(href)
                    if not normalized_url:
                        continue

                    if normalized_url in seen_urls:
                        continue
                    seen_urls.add(normalized_url)

                    text = " ".join(
                        a.get_text(
                            " ",
                            strip=True,
                        ).split()
                    )

                    node = a
                    best_context = text

                    for _ in range(7):
                        node = node.parent
                        if not node:
                            break

                        context = " ".join(
                            node.get_text(
                                " ",
                                strip=True,
                            ).split()
                        )

                        if (
                            len(context) > len(best_context)
                            and len(context) <= 1800
                        ):
                            best_context = context

                        if re.search(
                            r"(?:€\s*)?\d{1,4}[.,]\d{2}(?:\s*€)?",
                            context,
                        ):
                            break

                    relevant_to_query = relevant(
                        best_context + " " + normalized_url,
                        query,
                    )
                    has_price = bool(
                        re.search(
                            r"(?:€\s*)?\d{1,4}[.,]\d{2}(?:\s*€)?",
                            best_context,
                        )
                    )

                    entry = {
                        "url": normalized_url,
                        "raw_href": raw_href[:1000],
                        "text": text[:500],
                        "context": best_context[:1800],
                        "relevant_to_query": relevant_to_query,
                        "has_price": has_price,
                    }

                    product_links.append(entry)
                    if relevant_to_query:
                        relevant_links.append(entry)
                    if has_price:
                        priced_links.append(entry)

                pages.append(
                    {
                        "requested": rasasi_endpoint,
                        "type": "rasasi_catalog",
                        "status_code": r.status_code,
                        "final_url": r.url,
                        "html_length": len(html),
                        "product_url_count": len(product_links),
                        "relevant_product_url_count": len(relevant_links),
                        "priced_product_url_count": len(priced_links),
                        "product_urls": product_links[:100],
                        "relevant_product_urls": relevant_links[:100],
                        "priced_product_urls": priced_links[:100],
                    }
                )

            except Exception as exc:
                pages.append(
                    {
                        "requested": rasasi_endpoint,
                        "type": "rasasi_catalog",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )

            # Run the ACTUAL scraper discovery too.
            candidates = discover(
                session,
                query,
            )

            return {
                "diagnostic": True,
                "ok": True,
                "store": "Deloox",
                "query": query,
                "pages": pages,
                "discover_candidate_count": len(
                    candidates
                ),
                "discover_candidates": [
                    {
                        "url": url,
                        "score": info[0],
                        "context": info[1][:1800],
                        "is_product_url": bool(
                            is_product_url(url)
                        ),
                    }
                    for url, info in candidates
                ],
            }

        finally:
            session.close()

    except Exception as exc:
        return {
            "diagnostic": True,
            "ok": False,
            "store": "Deloox",
            "query": q,
            "stage": "debug_deloox",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
