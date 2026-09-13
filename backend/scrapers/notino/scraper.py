from __future__ import annotations

import html as html_lib
import json
import os
import re
import time
from urllib.parse import quote_plus, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except ImportError:
    PlaywrightTimeoutError = Exception
    sync_playwright = None

from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/debug", tags=["debug"])

BASE_URL = "https://www.notino.fr"
SEARCH_URL = BASE_URL + "/search.asp?exps={}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}

PRODUCT_RE = re.compile(r"/[^?#\s]*/p-\d+/?(?:$|[?#])", re.I)
PRICE_RE = re.compile(
    r"(?<![\d.,])(\d{1,4}(?:[ .]\d{3})*(?:[,.]\d{2})?)\s*(?:€|EUR)",
    re.I,
)

CHALLENGE_MARKERS = (
    "just a moment",
    "cf-chl-",
    "challenge-platform",
    "checking your browser",
    "verify you are human",
    "enable javascript and cookies",
    "vérification de sécurité",
    "access denied",
    "forbidden",
)

BLOCKED_PATHS = (
    "/search",
    "/panier",
    "/cart",
    "/login",
    "/compte",
    "/account",
    "/contact",
    "/marques",
    "/magazine",
)


def clean(value) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(str(value or ""))).strip()


def norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", clean(value).lower()).strip()


def tokens(value):
    return {x for x in norm(value).split() if len(x) > 1}


def query_match(text, query):
    q = tokens(query)
    t = tokens(text)
    return bool(q) and q.issubset(t)


def normalise_url(raw):
    value = clean(raw)
    value = value.replace("\\/", "/").replace("\\u002F", "/")
    value = unquote(value).strip(" <>\"'()[]{}.,;")

    if value.startswith("//"):
        value = "https:" + value
    elif value.startswith("/"):
        value = urljoin(BASE_URL, value)

    try:
        parsed = urlparse(value)
    except Exception:
        return None

    if parsed.netloc.lower() not in {"notino.fr", "www.notino.fr"}:
        return None

    path = parsed.path.rstrip("/")
    if not path or any(path.lower().startswith(x) for x in BLOCKED_PATHS):
        return None

    return f"https://www.notino.fr{path}"


def productish(url):
    if not url:
        return False
    path = urlparse(url).path.rstrip("/")
    if PRODUCT_RE.search(path):
        return True

    parts = [x for x in path.split("/") if x]
    return len(parts) >= 2 and len(tokens(parts[-1].replace("-", " "))) >= 2


def challenge(text):
    low = clean(text).lower()
    return [marker for marker in CHALLENGE_MARKERS if marker in low]


def page_summary(body):
    soup = BeautifulSoup(body or "", "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    h1 = soup.find("h1")
    return {
        "title": clean(title),
        "h1": clean(h1.get_text(" ", strip=True)) if h1 else "",
        "html_bytes": len((body or "").encode("utf-8")),
        "challenge_markers": challenge(body or ""),
        "has_json_ld": bool(soup.select('script[type="application/ld+json"]')),
        "anchor_count": len(soup.find_all("a", href=True)),
    }


def raw_links(body):
    soup = BeautifulSoup(body or "", "html.parser")
    found = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        url = normalise_url(anchor.get("href"))
        if not url or url in seen:
            continue
        seen.add(url)
        found.append({
            "url": url,
            "text": clean(anchor.get_text(" ", strip=True)),
            "title": clean(anchor.get("title")),
            "aria": clean(anchor.get("aria-label")),
            "productish": productish(url),
        })

    return found


def jsonld_products(body):
    soup = BeautifulSoup(body or "", "html.parser")
    products = []

    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue

        for obj in walk(data):
            if not isinstance(obj, dict):
                continue
            typ = obj.get("@type")
            if typ == "Product" or (
                isinstance(typ, list) and "Product" in typ
            ):
                products.append({
                    "name": clean(obj.get("name")),
                    "url": clean(obj.get("url") or obj.get("@id")),
                    "sku": clean(obj.get("sku")),
                    "gtin": clean(obj.get("gtin13") or obj.get("gtin")),
                    "brand": (
                        clean(obj.get("brand", {}).get("name"))
                        if isinstance(obj.get("brand"), dict)
                        else clean(obj.get("brand"))
                    ),
                    "offers": obj.get("offers"),
                })

    return products


def extract_prices(text):
    return [m.group(1) for m in PRICE_RE.finditer(clean(text))]


def inspect_product(session, url, query):
    result = {
        "url": url,
        "http": {},
        "browser": None,
        "identity": {},
        "prices": [],
        "decision": "not_checked",
        "reason": "",
    }

    try:
        started = time.monotonic()
        response = session.get(
            url,
            headers=HEADERS,
            timeout=10,
            allow_redirects=True,
        )
        result["http"] = {
            "status": response.status_code,
            "final_url": response.url,
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "html_bytes": len(response.content),
            "content_type": response.headers.get("content-type", ""),
        }

        body = response.text if response.status_code < 400 else ""
        if body:
            summary = page_summary(body)
            result["identity"]["http"] = {
                "h1": summary["h1"],
                "title": summary["title"],
                "challenge_markers": summary["challenge_markers"],
            }
            result["prices"] = extract_prices(body)

            names = [x["name"] for x in jsonld_products(body) if x["name"]]
            result["identity"]["jsonld_names"] = names

            identity_text = " ".join(
                [summary["h1"], summary["title"], " ".join(names)]
            )

            if query_match(identity_text, query):
                result["decision"] = "accepted_by_identity"
                result["reason"] = "HTTP product page contains a matching product identity"
                return result

        if response.status_code >= 400:
            result["reason"] = f"HTTP product request returned {response.status_code}"

    except requests.RequestException as exc:
        result["http"] = {
            "status": None,
            "error": f"{type(exc).__name__}: {exc}",
        }

    if sync_playwright is None:
        result["browser"] = {"attempted": False, "reason": "playwright_not_installed"}
        if result["decision"] == "not_checked":
            result["decision"] = "blocked_or_unreadable"
        return result

    try:
        started = time.monotonic()

        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
            context = browser.new_context(
                user_agent=USER_AGENT,
                locale="fr-FR",
                extra_http_headers={
                    "Accept-Language": HEADERS["Accept-Language"]
                },
                viewport={"width": 1365, "height": 900},
            )
            page = context.new_page()

            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=20000,
            )

            try:
                page.wait_for_selector(
                    "h1, script[type='application/ld+json']",
                    state="attached",
                    timeout=7000,
                )
            except PlaywrightTimeoutError:
                pass

            page.wait_for_timeout(700)
            body = page.content()

            browser_report = {
                "attempted": True,
                "status": response.status if response else None,
                "final_url": page.url,
                "elapsed_ms": round((time.monotonic() - started) * 1000),
                "html_bytes": len(body.encode("utf-8")),
                "challenge_markers": challenge(body),
            }

            summary = page_summary(body)
            names = [x["name"] for x in jsonld_products(body) if x["name"]]

            result["browser"] = browser_report
            result["identity"]["browser"] = {
                "h1": summary["h1"],
                "title": summary["title"],
                "jsonld_names": names,
            }

            result["prices"] = result["prices"] or extract_prices(body)

            identity_text = " ".join(
                [summary["h1"], summary["title"], " ".join(names)]
            )

            if query_match(identity_text, query):
                result["decision"] = "accepted_by_browser_identity"
                result["reason"] = "Browser-rendered product page contains a matching identity"
            elif result["decision"] == "not_checked":
                if browser_report["challenge_markers"]:
                    result["decision"] = "blocked_by_challenge"
                    result["reason"] = "Browser received a challenge/block page"
                else:
                    result["decision"] = "no_identity_match"
                    result["reason"] = "Product page loaded but query did not match the extracted identity"

            browser.close()

    except Exception as exc:
        result["browser"] = {
            "attempted": True,
            "error": f"{type(exc).__name__}: {exc}",
        }
        if result["decision"] == "not_checked":
            result["decision"] = "browser_error"
            result["reason"] = f"{type(exc).__name__}: {exc}"

    return result


def diagnose(query):
    query = clean(query)
    started = time.monotonic()

    report = {
        "diagnostic_version": "notino-real-diagnostic-1.0",
        "query": query,
        "search_url": SEARCH_URL.format(quote_plus(query)),
        "http_search": {},
        "http_candidates": [],
        "playwright_search": {},
        "playwright_candidates": [],
        "candidate_intersection": [],
        "product_checks": [],
        "conclusion": {},
    }

    session = requests.Session()

    # ------------------------------------------------------------
    # 1. DIRECT HTTP REQUEST TO NOTINO SEARCH
    # ------------------------------------------------------------
    try:
        t0 = time.monotonic()
        response = session.get(
            report["search_url"],
            headers=HEADERS,
            timeout=12,
            allow_redirects=True,
        )
        body = response.text or ""

        report["http_search"] = {
            "status": response.status_code,
            "final_url": response.url,
            "elapsed_ms": round((time.monotonic() - t0) * 1000),
            "headers": {
                "content_type": response.headers.get("content-type", ""),
                "server": response.headers.get("server", ""),
                "cf_ray": response.headers.get("cf-ray", ""),
            },
            "page": page_summary(body),
            "body_preview": clean(
                BeautifulSoup(body, "html.parser").get_text(" ", strip=True)
            )[:500],
        }

        links = raw_links(body)
        report["http_candidates"] = [
            x for x in links if x["productish"]
        ][:50]

    except Exception as exc:
        report["http_search"] = {
            "status": None,
            "error": f"{type(exc).__name__}: {exc}",
        }

    # ------------------------------------------------------------
    # 2. REAL BROWSER REQUEST TO THE SAME NOTINO SEARCH URL
    # ------------------------------------------------------------
    if sync_playwright is None:
        report["playwright_search"] = {
            "attempted": False,
            "error": "playwright_not_installed",
        }
    else:
        try:
            t0 = time.monotonic()

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                    ],
                )

                context = browser.new_context(
                    user_agent=USER_AGENT,
                    locale="fr-FR",
                    extra_http_headers={
                        "Accept-Language": HEADERS["Accept-Language"]
                    },
                    viewport={"width": 1365, "height": 900},
                )

                page = context.new_page()

                response = page.goto(
                    report["search_url"],
                    wait_until="domcontentloaded",
                    timeout=25000,
                )

                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=8000,
                    )
                except PlaywrightTimeoutError:
                    pass

                page.wait_for_timeout(800)

                body = page.content()
                links = raw_links(body)

                report["playwright_search"] = {
                    "attempted": True,
                    "status": response.status if response else None,
                    "final_url": page.url,
                    "elapsed_ms": round((time.monotonic() - t0) * 1000),
                    "page": page_summary(body),
                    "product_links": [
                        x for x in links if x["productish"]
                    ][:50],
                }

                report["playwright_candidates"] = [
                    x for x in links if x["productish"]
                ][:50]

                browser.close()

        except Exception as exc:
            report["playwright_search"] = {
                "attempted": True,
                "error": f"{type(exc).__name__}: {exc}",
            }

    # ------------------------------------------------------------
    # 3. COMPARE HTTP AND BROWSER DISCOVERY
    # ------------------------------------------------------------
    http_urls = {
        x["url"] for x in report["http_candidates"]
    }
    browser_urls = {
        x["url"] for x in report["playwright_candidates"]
    }

    report["candidate_intersection"] = sorted(
        http_urls.intersection(browser_urls)
    )

    # ------------------------------------------------------------
    # 4. INSPECT UP TO 5 REAL PRODUCT CANDIDATES
    # ------------------------------------------------------------
    candidate_urls = []
    for url in list(browser_urls) + list(http_urls):
        if url not in candidate_urls:
            candidate_urls.append(url)

    for url in candidate_urls[:5]:
        report["product_checks"].append(
            inspect_product(session, url, query)
        )

    # ------------------------------------------------------------
    # 5. AUTOMATIC CONCLUSION
    # ------------------------------------------------------------
    http_status = report["http_search"].get("status")
    browser_status = report["playwright_search"].get("status")
    http_count = len(report["http_candidates"])
    browser_count = len(report["playwright_candidates"])
    product_count = len(report["product_checks"])

    http_challenge = report["http_search"].get("page", {}).get(
        "challenge_markers", []
    )
    browser_challenge = report["playwright_search"].get("page", {}).get(
        "challenge_markers", []
    )

    accepted = [
        x for x in report["product_checks"]
        if x.get("decision", "").startswith("accepted")
    ]

    if http_status == 403 and browser_status == 403:
        cause = "NOTINO_BLOCKS_RENDER"
        explanation = (
            "Both direct HTTP and real-browser access to the Notino search "
            "endpoint return HTTP 403."
        )
    elif http_status == 403 and browser_count == 0:
        cause = "NOTINO_BLOCKS_HTTP_AND_BROWSER_HAS_NO_PRODUCTS"
        explanation = (
            "Direct HTTP is blocked with 403 and the browser did not expose "
            "usable product candidates."
        )
    elif browser_challenge:
        cause = "BROWSER_CHALLENGE"
        explanation = (
            "The browser reached Notino but the returned document contains "
            "challenge/block markers."
        )
    elif http_count == 0 and browser_count == 0:
        cause = "NO_DISCOVERY_CANDIDATES"
        explanation = (
            "Neither HTTP nor browser discovery exposed product URLs. "
            "The next investigation should target the transport/discovery "
            "route, not the product parser."
        )
    elif (http_count or browser_count) and not accepted:
        cause = "PRODUCT_PAGE_OR_IDENTITY_PROBLEM"
        explanation = (
            "Product-looking URLs were discovered, but the inspected product "
            "pages did not produce a matching identity."
        )
    elif accepted:
        cause = "DISCOVERY_AND_PRODUCT_ACCESS_WORK"
        explanation = (
            "At least one real Notino product page was reachable and its "
            "identity matched the query."
        )
    else:
        cause = "UNDETERMINED"
        explanation = "The diagnostic did not collect enough evidence."

    report["conclusion"] = {
        "cause": cause,
        "explanation": explanation,
        "http_search_status": http_status,
        "browser_search_status": browser_status,
        "http_product_candidates": http_count,
        "browser_product_candidates": browser_count,
        "products_inspected": product_count,
        "products_accepted": len(accepted),
        "http_challenge_markers": http_challenge,
        "browser_challenge_markers": browser_challenge,
        "total_elapsed_ms": round((time.monotonic() - started) * 1000),
    }

    session.close()
    return report


@router.get("/notino")
def debug_notino(q: str = Query(..., min_length=2)):
    try:
        return {
            "ok": True,
            **diagnose(q),
        }
    except Exception as exc:
        return {
            "ok": False,
            "query": q,
            "error": f"{type(exc).__name__}: {exc}",
            "error_code": "diagnostic_runtime_error",
        }
