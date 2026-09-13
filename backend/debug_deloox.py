from __future__ import annotations

import traceback
from urllib.parse import quote_plus, urljoin

import requests
from bs4 import BeautifulSoup
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])


@router.get("/deloox")
def debug_deloox(q: str = Query(..., min_length=2)):
    """
    Diagnostica temporanea Deloox.

    NON modifica il comportamento dello scraper.
    Mostra:
    - pagine realmente ricevute da Deloox
    - URL finali dopo eventuali redirect
    - link contenenti Liquid/Brun/Limited/Edition
    - se ogni URL viene riconosciuto come product URL
    - risultato di product_url()
    - risultato di relevant()
    - candidati prodotti restituiti da discover()
    """
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
        seen = set()

        try:
            for endpoint in endpoints:
                try:
                    r = session.get(
                        endpoint,
                        headers=HEADERS,
                        timeout=TIMEOUT,
                        allow_redirects=True,
                    )

                    page = {
                        "requested": endpoint,
                        "status_code": r.status_code,
                        "final_url": r.url,
                        "html_length": len(r.text or ""),
                    }

                    if (
                        r.status_code == 200
                        and r.text
                        and r.url not in seen
                    ):
                        seen.add(r.url)

                        soup = BeautifulSoup(
                            r.text,
                            "html.parser",
                        )

                        links = []

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

                            href = urljoin(
                                r.url,
                                a.get("href", ""),
                            )

                            blob = (
                                f"{text} {href}"
                            ).lower()

                            if any(
                                term in blob
                                for term in (
                                    "liquid",
                                    "brun",
                                    "limited",
                                    "edition",
                                )
                            ):
                                normalized = product_url(
                                    href
                                )

                                links.append(
                                    {
                                        "text": text[:500],
                                        "href": href[:1000],
                                        "is_product_url": bool(
                                            is_product_url(href)
                                        ),
                                        "product_url": normalized,
                                        "relevant_to_query": relevant(
                                            f"{text} {href}",
                                            query,
                                        ),
                                    }
                                )

                        page["matching_links"] = links[:100]

                    pages.append(page)

                except Exception as exc:
                    pages.append(
                        {
                            "requested": endpoint,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )

            candidates = discover(
                session,
                query,
            )

            return {
                "diagnostic": True,
                "ok": True,
                "store": "Deloox",
                "query": query,
                "token_check": sorted(
                    set(query.lower().split())
                ),
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
