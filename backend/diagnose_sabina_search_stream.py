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


def _decode_state(state):
    raw = state or ""
    try:
        pad = "=" * (-len(raw) % 4)
        decoded = base64.urlsafe_b64decode((raw + pad).encode()).decode("utf-8")
        try:
            return json.loads(decoded)
        except Exception:
            from urllib.parse import unquote
            return json.loads(unquote(decoded))
    except Exception:
        return None


@router.get("/diagnose-sabina-js-search")
def diagnose_sabina_js_search(
    q: str = Query("Hawas", min_length=1, max_length=120),
):
    started = time.monotonic()
    try:
        from playwright.sync_api import sync_playwright

        state = {
            "facets": [],
            "selectorFacet": None,
            "tabFacet": None,
            "sorting": {"field": "relevance", "type": "desc"},
            "searchText": q,
            "priceFacet": None,
        }
        encoded = base64.urlsafe_b64encode(
            json.dumps(state, separators=(",", ":"), ensure_ascii=False).encode()
        ).decode().rstrip("=")
        url = "https://www.sabina.com/it/#" + encoded

        requests = []
        responses = []
        products = []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            def on_request(req):
                u = req.url
                if req.resource_type in {"xhr", "fetch"} or any(x in u.lower() for x in ("search", "api", "ajax", "product", "catalog")):
                    body = req.post_data
                    requests.append({
                        "method": req.method,
                        "url": u,
                        "resource_type": req.resource_type,
                        "post_data": body[:4000] if body else None,
                    })

            def on_response(resp):
                req = resp.request
                u = resp.url
                if req.resource_type in {"xhr", "fetch"} or any(x in u.lower() for x in ("search", "api", "ajax", "product", "catalog")):
                    responses.append({
                        "status": resp.status,
                        "url": u,
                        "resource_type": req.resource_type,
                        "content_type": resp.headers.get("content-type"),
                    })
                    try:
                        if "json" in (resp.headers.get("content-type") or "").lower():
                            data = resp.json()
                            text = json.dumps(data, ensure_ascii=False)[:20000]
                            if q.lower() in text.lower() or "kobra" in text.lower():
                                products.append({"url": u, "status": resp.status, "json_sample": data})
                    except Exception:
                        pass

            page.on("request", on_request)
            page.on("response", on_response)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(8000)

            body_text = page.locator("body").inner_text(timeout=5000)
            browser.close()

        return {
            "diagnostic": "sabina-js-search-network-v1",
            "ok": True,
            "query": q,
            "search_url": url,
            "decoded_state": state,
            "network_requests": requests,
            "network_responses": responses,
            "matching_json_responses": products,
            "page_contains_query": q.lower() in body_text.lower(),
            "page_contains_kobra": "kobra" in body_text.lower(),
            "page_text_sample": body_text[:12000],
            "read_only": True,
            "catalog_written": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
    except Exception as exc:
        return {
            "diagnostic": "sabina-js-search-network-v1",
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "read_only": True,
            "catalog_written": False,
            "elapsed_sec": round(time.monotonic() - started, 3),
        }
