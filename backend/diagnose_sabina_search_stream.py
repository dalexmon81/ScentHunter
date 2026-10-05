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
    started = time.monotonic()
    url = _sabina_search_url(q)
    requests = []
    responses = []
    matching_json = []
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
                )
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
                        "post_data": body[:8000] if body else None,
                    })

            def on_response(resp):
                req = resp.request
                u = resp.url
                if req.resource_type in {"xhr", "fetch"} or any(
                    x in u.lower() for x in ("search", "api", "ajax", "product", "catalog")
                ):
                    content_type = resp.headers.get("content-type") or ""
                    responses.append({
                        "status": resp.status,
                        "url": u,
                        "resource_type": req.resource_type,
                        "content_type": content_type,
                    })
                    if "json" in content_type.lower():
                        try:
                            data = resp.json()
                            compact = json.dumps(data, ensure_ascii=False)
                            if q.lower() in compact.lower() or "kobra" in compact.lower() or "hawas" in compact.lower():
                                matching_json.append({
                                    "url": u,
                                    "status": resp.status,
                                    "json_sample": data,
                                })
                        except Exception:
                            pass

            context.on("request", on_request)
            context.on("response", on_response)

            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
            except PlaywrightTimeoutError as exc:
                navigation_error = f"PlaywrightTimeoutError: {exc}"

            # The search is client-side and may fire after initial DOM load.
            page.wait_for_timeout(10000)

            try:
                body_text = page.locator("body").inner_text(timeout=5000)
            except Exception:
                body_text = ""

            context.close()
            browser.close()

        return {
            "diagnostic": "sabina-js-search-network-v2",
            "ok": True,
            "query": q,
            "search_url": url,
            "navigation_error": navigation_error,
            "network_requests": requests,
            "network_responses": responses,
            "matching_json_responses": matching_json,
            "page_contains_query": q.lower() in body_text.lower(),
            "page_contains_kobra": "kobra" in body_text.lower(),
            "page_text_sample": body_text[:12000],
            "read_only": True,
            "catalog_written": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        return {
            "diagnostic": "sabina-js-search-network-v2",
            "ok": False,
            "query": q,
            "search_url": url,
            "error": f"{type(exc).__name__}: {exc}",
            "network_requests": requests,
            "network_responses": responses,
            "matching_json_responses": matching_json,
            "read_only": True,
            "catalog_written": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
