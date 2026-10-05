"""ScentHunter - Sabina Italian JS search network diagnostic.

Read-only diagnostic. Opens Sabina's real Italian homepage search state with
Playwright and records network requests generated while the page searches.
No catalog, matcher, scraper or database writes.
"""
import base64
import json
import time
from urllib.parse import quote
from fastapi import APIRouter, Query

router = APIRouter()


def _sabina_search_url(query: str) -> str:
    state = {
        "facets": [],
        "selectorFacet": None,
        "tabFacet": None,
        "sorting": {"field": "relevance", "type": "desc"},
        "searchText": query,
        "priceFacet": None,
    }
    # Sabina's Italian search fragment is base64(URL-encoded JSON), not
    # base64(raw JSON). This reproduces the format of the real browser URL.
    encoded_json = quote(
        json.dumps(state, separators=(",", ":"), ensure_ascii=False),
        safe="",
    )
    encoded = base64.b64encode(encoded_json.encode("utf-8")).decode("ascii").rstrip("=")
    return "https://www.sabina.com/it/#" + encoded


@router.get("/diagnose-sabina-js-search")
def diagnose_sabina_js_search(
    q: str = Query("Hawas", min_length=1, max_length=120),
):
    """Read-only, bounded network trace of Sabina's Italian JS search.

    Important: response bodies are deliberately NOT parsed inside Playwright
    response callbacks. That was causing the previous diagnostic to hang on
    large/streamed JSON responses.
    """
    started = time.monotonic()
    url = _sabina_search_url(q)
    requests = []
    responses = []
    body_text = ""
    navigation_error = None

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
                ),
                service_workers="block",
            )
            page = context.new_page()

            def on_request(req):
                u = req.url
                if req.resource_type in {"xhr", "fetch"} or any(
                    x in u.lower() for x in ("search", "api", "ajax", "product", "catalog")
                ):
                    body = req.post_data
                    requests.append({
                        "method": req.method,
                        "url": u,
                        "resource_type": req.resource_type,
                        "post_data": body[:6000] if body else None,
                    })

            def on_response(resp):
                req = resp.request
                u = resp.url
                if req.resource_type in {"xhr", "fetch"} or any(
                    x in u.lower() for x in ("search", "api", "ajax", "product", "catalog")
                ):
                    responses.append({
                        "status": resp.status,
                        "url": u,
                        "resource_type": req.resource_type,
                        "content_type": resp.headers.get("content-type"),
                    })

            context.on("request", on_request)
            context.on("response", on_response)

            # Do not wait for every network request. We only need the JS calls.
            try:
                page.goto(url, wait_until="commit", timeout=10000)
            except PlaywrightTimeoutError as exc:
                navigation_error = f"PlaywrightTimeoutError: {exc}"

            page.wait_for_timeout(5000)

            try:
                body_text = page.locator("body").inner_text(timeout=2000)
            except Exception:
                body_text = ""

            context.close()
            browser.close()

        return {
            "diagnostic": "sabina-js-search-network-v3",
            "ok": True,
            "query": q,
            "search_url": url,
            "navigation_error": navigation_error,
            "request_count": len(requests),
            "response_count": len(responses),
            "network_requests": requests,
            "network_responses": responses,
            "page_contains_query": q.lower() in body_text.lower(),
            "page_contains_kobra": "kobra" in body_text.lower(),
            "page_text_sample": body_text[:6000],
            "read_only": True,
            "catalog_written": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        return {
            "diagnostic": "sabina-js-search-network-v3",
            "ok": False,
            "query": q,
            "search_url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "request_count": len(requests),
            "response_count": len(responses),
            "network_requests": requests,
            "network_responses": responses,
            "read_only": True,
            "catalog_written": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
