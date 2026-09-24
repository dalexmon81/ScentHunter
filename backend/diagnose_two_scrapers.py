from fastapi import APIRouter, Query
import concurrent.futures
import json
import re
import time
from urllib.parse import quote, urljoin

import requests

router = APIRouter()

UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"
HEADERS = {"User-Agent": UA, "Accept-Language": "it-IT,it;q=0.9,en;q=0.8"}
TOKEN_RE = re.compile(r"\b(liquid|brun)\b", re.I)

def _get(url, timeout=(1.5, 5.0), headers=None):
    t = time.monotonic()
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=timeout, allow_redirects=True)
        return {
            "ok": True,
            "status": r.status_code,
            "url": r.url,
            "elapsed_sec": round(time.monotonic()-t, 3),
            "bytes": len(r.content),
            "text": r.text,
            "error": None,
        }
    except Exception as e:
        return {
            "ok": False,
            "status": None,
            "url": url,
            "elapsed_sec": round(time.monotonic()-t, 3),
            "bytes": 0,
            "text": "",
            "error": f"{type(e).__name__}: {e}",
        }

def _compact(s, n=500):
    s = re.sub(r"\s+", " ", s or "").strip()
    return s[:n]

@router.get("/diagnose-sabina-catalog")
def diagnose_sabina_precise(q: str = Query("Liquid Brun")):
    base = "https://www.sabina.com"
    urls = [
        f"{base}/it/ricerca_old?s={quote(q)}",
        f"{base}/it/ricerca?search_query={quote(q)}",
        f"{base}/it/ricerca_old?search_query={quote(q)}",
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda u: _get(u), urls))

    probes = []
    for p in pages:
        text = p["text"]
        low = text.lower()
        hits = {}
        for marker in [q, "liquid brun", "liquid-brun", "34982", "720100",
                       "french avenue", "profumi-da-uomo", "/it/profumi-da-uomo/"]:
            i = low.find(marker.lower())
            hits[marker] = None if i < 0 else {
                "offset": i,
                "context": _compact(text[max(0, i-350):i+700], 1050)
            }

        # Inspect links around product-like references.
        links = []
        for m in re.finditer(r'href=["\']([^"\']+)["\']', text, re.I):
            href = m.group(1)
            if any(x in href.lower() for x in ["34982", "liquid", "brun", "profumi-da-uomo"]):
                links.append(urljoin(p["url"], href))
        probes.append({
            "url": p["url"],
            "status": p["status"],
            "elapsed_sec": p["elapsed_sec"],
            "bytes": p["bytes"],
            "error": p["error"],
            "markers": hits,
            "matching_links": list(dict.fromkeys(links))[:50],
        })

    return {
        "diagnostic": True,
        "store": "Sabina",
        "query": q,
        "elapsed_sec": round(time.monotonic()-started, 3),
        "purpose": "read-only inspection of real search responses; no production search() and no product-specific rule",
        "probes": probes,
    }


@router.get("/diagnose-sabina-html")
def diagnose_sabina_html(qs: str = Query("9 PM|Liquid Brun|Hawas")):
    """Read-only structural inspection of Sabina search HTML.

    This endpoint deliberately bypasses production discovery. It shows the
    real HTML/DOM context around each query occurrence and nearby product
    URLs/attributes so discovery differences can be diagnosed without
    adding product-specific rules.
    """
    from bs4 import BeautifulSoup
    from html import unescape

    started = time.monotonic()
    queries = []
    seen = set()

    for raw in (qs or "").split("|")[:8]:
        q = raw.strip()
        if q and q.casefold() not in seen:
            seen.add(q.casefold())
            queries.append(q)

    base = "https://www.sabina.com"
    search_url = base + "/es/buscar"

    result = {
        "diagnostic": True,
        "store": "Sabina",
        "queries": queries,
        "purpose": (
            "Read-only inspection of the real Sabina search HTML. "
            "This endpoint does not call production discovery."
        ),
        "query_results": [],
    }

    for q in queries:
        t0 = time.monotonic()

        try:
            response = requests.get(
                search_url,
                params={"search_query": q},
                headers=HEADERS,
                timeout=(2.5, 12.0),
                allow_redirects=True,
            )
            html = response.text or ""
        except Exception as exc:
            result["query_results"].append({
                "query": q,
                "http": {
                    "ok": False,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            })
            continue

        low = html.casefold()
        qlow = q.casefold()
        raw_occurrences = []

        # Exact literal occurrences in the raw response.
        for match in list(re.finditer(re.escape(qlow), low))[:20]:
            start = max(0, match.start() - 1200)
            end = min(len(html), match.end() + 1800)
            raw = html[start:end]

            nearby_urls = []

            # Any common URL-bearing HTML attributes in the local context.
            for attr_match in re.finditer(
                r'(?:href|src|data-href|data-url|data-link|content)'
                r'\s*=\s*["\']([^"\']+)["\']',
                raw,
                re.I,
            ):
                candidate = unescape(attr_match.group(1))
                absolute = urljoin(response.url, candidate)
                if "sabina.com" in absolute.lower():
                    nearby_urls.append(absolute)

            # Raw absolute/relative Sabina URLs in the same context.
            for url_match in re.finditer(
                r'(?:https?:)?//(?:www\.)?sabina\.com/'
                r'(?:es|it|fr|en|de|nl|pt)/[^"\'<>\s\\]+',
                raw.replace("\\/", "/"),
                re.I,
            ):
                nearby_urls.append(
                    urljoin(response.url, unescape(url_match.group(0)))
                )

            raw_occurrences.append({
                "offset": match.start(),
                "context": _compact(raw, 3200),
                "nearby_urls": list(dict.fromkeys(nearby_urls))[:50],
            })

        # DOM-level inspection. For each text node containing the query,
        # walk up several ancestors and expose attributes + links.
        soup = BeautifulSoup(html, "html.parser")
        dom_hits = []

        for node in soup.find_all(string=re.compile(re.escape(q), re.I)):
            parent = node.parent
            if parent is None:
                continue

            chain = []
            current = parent

            for _ in range(6):
                if current is None or not getattr(current, "name", None):
                    break

                attrs = {}
                for key, value in current.attrs.items():
                    if isinstance(value, (list, tuple)):
                        value = " ".join(str(v) for v in value)
                    attrs[key] = str(value)

                links = []
                if current.name == "a" and current.get("href"):
                    links.append(
                        urljoin(response.url, current.get("href"))
                    )

                for anchor in current.find_all("a", href=True):
                    links.append(
                        urljoin(response.url, anchor.get("href"))
                    )

                chain.append({
                    "tag": current.name,
                    "attrs": attrs,
                    "text": _compact(
                        current.get_text(" ", strip=True),
                        1200,
                    ),
                    "links": list(dict.fromkeys(links))[:30],
                })

                current = current.parent

            dom_hits.append({
                "text": _compact(str(node), 500),
                "chain": chain,
            })

            if len(dom_hits) >= 20:
                break

        # Independent product-like URL extraction. This deliberately does
        # not apply the current scraper's relevance filter.
        product_urls = []

        decoded = (
            html
            .replace("\\u002F", "/")
            .replace("\\u002f", "/")
            .replace("\\/", "/")
        )

        for match in re.finditer(
            r'(?:https?:)?//(?:www\.)?sabina\.com/'
            r'(?:es|it|fr|en|de|nl|pt)/[^"\'<>\s\\]+',
            decoded,
            re.I,
        ):
            product_urls.append(
                urljoin(response.url, unescape(match.group(0)))
            )

        for match in re.finditer(
            r'/(?:es|it|fr|en|de|nl|pt)/[^"\'<>\s\\]+',
            decoded,
            re.I,
        ):
            product_urls.append(
                urljoin(response.url, unescape(match.group(0)))
            )

        result["query_results"].append({
            "query": q,
            "http": {
                "ok": True,
                "status": response.status_code,
                "url": response.url,
                "elapsed_sec": round(time.monotonic() - t0, 3),
                "bytes": len(response.content),
                "literal_occurrences": low.count(qlow),
            },
            "raw_occurrences": raw_occurrences,
            "dom_hits": dom_hits,
            "product_like_urls": list(dict.fromkeys(product_urls))[:100],
        })

        response.close()

    result["elapsed_sec"] = round(time.monotonic() - started, 3)
    return result

@router.get("/diagnose-deloox-catalog")
def diagnose_deloox_precise(q: str = Query("Liquid Brun")):
    urls = [
        "https://www.deloox.com/en/category/1121334/french-avenue-mens-fragrances.html",
        "https://www.deloox.com/en/category/1121322/french-avenue-fragrances.html",
        "https://www.deloox.com/en/category/1132834/liquid-brun.html",
    ]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
        pages = list(ex.map(lambda u: _get(u, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}), urls))

    out = []
    for p in pages:
        text = p["text"]
        low = text.lower()
        # Capture product-card-like anchors whose nearby text contains a query token.
        matches = []
        for m in re.finditer(r'<a\b[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', text, re.I | re.S):
            href, inner = m.group(1), m.group(2)
            visible = re.sub(r"<[^>]+>", " ", inner)
            visible = _compact(visible, 800)
            if TOKEN_RE.search(visible):
                matches.append({
                    "url": urljoin(p["url"], href),
                    "text": visible,
                })
        # Also locate raw occurrences in page text, independent of href.
        raw_contexts = []
        for m in list(TOKEN_RE.finditer(text))[:20]:
            raw_contexts.append(_compact(text[max(0, m.start()-300):m.end()+500], 900))
        out.append({
            "url": p["url"],
            "status": p["status"],
            "elapsed_sec": p["elapsed_sec"],
            "bytes": p["bytes"],
            "error": p["error"],
            "card_token_hits": matches[:50],
            "raw_token_contexts": raw_contexts,
        })

    return {
        "diagnostic": True,
        "store": "Deloox",
        "query": q,
        "elapsed_sec": round(time.monotonic()-started, 3),
        "purpose": "read-only inspection of category/card text; no URL-token discovery and no production search()",
        "pages": out,
    }
