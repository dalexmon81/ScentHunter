"""
ScentHunter — Sabina forensic diagnostic
----------------------------------------
DIAGNOSTIC ONLY. This file does NOT modify the production scraper.

Purpose:
- test the exact Sabina search endpoint used by ScentHunter;
- preserve HTTP/redirect/timeout/block information;
- show whether the returned HTML actually contains product URLs;
- test the three queries that matter for the current Sabina incident.

Run from the ScentHunter backend environment:

    python diagnose_sabina_runtime.py

Optional:
    python diagnose_sabina_runtime.py "9 PM"
    python diagnose_sabina_runtime.py "Liquid Brun" "Hawas"

No product-specific URLs, prices or matcher rules are used.
"""

import json
import re
import sys
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.sabina.com"
SEARCH_URL = BASE_URL + "/es/buscar"
TIMEOUT = 20

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Referer": BASE_URL + "/es/",
}

PRODUCT_RE = re.compile(
    r"/(?:es|it|fr|en|de|nl|pt)/[^/]+/\d+-[^/]+\.html",
    re.I,
)


def normalise_url(raw, base):
    if not raw:
        return None
    raw = str(raw).strip().replace("\\/", "/").replace("\\u002F", "/")
    url = urljoin(base, raw)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return None
    if parsed.netloc.lower() not in ("sabina.com", "www.sabina.com"):
        return None
    return url


def extract_product_urls(html, response_url):
    soup = BeautifulSoup(html, "html.parser")
    found = []
    seen = set()

    def add(raw):
        url = normalise_url(raw, response_url)
        if not url:
            return
        if not PRODUCT_RE.search(urlparse(url).path):
            return
        key = url.rstrip("/")
        if key in seen:
            return
        seen.add(key)
        found.append(key)

    # Real anchors.
    for a in soup.find_all("a", href=True):
        add(a.get("href"))

    # URLs embedded in HTML/JSON.
    decoded = html.replace("\\/", "/").replace("\\u002F", "/")

    for m in re.finditer(
        r'https?://(?:www\.)?sabina\.com/'
        r'(?:es|it|fr|en|de|nl|pt)/'
        r'[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(m.group(0))

    for m in re.finditer(
        r'/(?:es|it|fr|en|de|nl|pt)/'
        r'[^"\'<>\s\\]+',
        decoded,
        re.I,
    ):
        add(m.group(0))

    return found


def run(query):
    session = requests.Session()

    result = {
        "query": query,
        "request": {
            "url": SEARCH_URL,
            "params": {"search_query": query},
            "timeout": TIMEOUT,
        },
        "http": {},
        "discovery": {},
        "sample": "",
        "error": None,
    }

    try:
        response = session.get(
            SEARCH_URL,
            params={"search_query": query},
            headers=HEADERS,
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        result["http"] = {
            "status_code": response.status_code,
            "reason": response.reason,
            "requested_url": response.request.url if response.request else None,
            "final_url": response.url,
            "redirected": response.url != response.request.url
            if response.request
            else None,
            "content_type": response.headers.get("content-type"),
            "content_length_header": response.headers.get("content-length"),
            "body_bytes": len(response.content),
            "server": response.headers.get("server"),
            "location": response.headers.get("location"),
        }

        result["sample"] = response.text[:1000]

        if response.status_code >= 400:
            result["discovery"] = {
                "verified": False,
                "status": "http_error",
                "reason": "HTTP status >= 400",
                "product_url_count": 0,
            }
            return result

        urls = extract_product_urls(response.text, response.url)

        result["discovery"] = {
            "verified": bool(urls),
            "status": "success" if urls else "empty",
            "product_url_count": len(urls),
            "product_urls": urls[:30],
        }

        return result

    except requests.Timeout as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        result["discovery"] = {
            "verified": False,
            "status": "timeout",
        }
        return result

    except requests.ConnectionError as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        result["discovery"] = {
            "verified": False,
            "status": "unavailable",
        }
        return result

    except requests.RequestException as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
        result["discovery"] = {
            "verified": False,
            "status": "error",
        }
        return result

    finally:
        session.close()


def main():
    queries = sys.argv[1:] or [
        "9 PM",
        "Liquid Brun",
        "Hawas",
    ]

    print(
        json.dumps(
            [run(query) for query in queries],
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
