from fastapi import APIRouter, Query
import time
import urllib.parse

router = APIRouter()

TARGETS = {
    "donna_50": {
        "url": "https://www.easycosmetic.be/valentino/donna-born-in-roma/valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx?variant=78098",
        "tokens": ["valentino", "donna", "born", "roma", "coral", "fantasy"],
    },
    "donna_100": {
        "url": "https://www.easycosmetic.be/valentino/donna-born-in-roma/valentino-donna-born-in-roma-coral-fantasy-eau-de-parfum-spray.aspx?variant=78099",
        "tokens": ["valentino", "donna", "born", "roma", "coral", "fantasy"],
    },
    "uomo_100": {
        "url": "",
        "tokens": ["valentino", "uomo", "born", "roma", "coral", "fantasy"],
    },
}


def _row_dict(row):
    return dict(row) if row is not None else None


def _url_path(url):
    try:
        return urllib.parse.urlparse(str(url or "")).path.rstrip("/").lower()
    except Exception:
        return ""


def _query_rows(conn, table, url, store="easycosmetic", limit=25):
    # Table names are fixed internally; never taken from request parameters.
    exact = conn.execute(
        f"SELECT * FROM {table} WHERE store=? AND url=? LIMIT 10",
        (store, url),
    ).fetchall()
    path = _url_path(url)
    variants = conn.execute(
        f"SELECT * FROM {table} WHERE store=? AND lower(url) LIKE ? ORDER BY url LIMIT ?",
        (store, f"%{path}", limit),
    ).fetchall() if path else []
    return {
        "exact": [_row_dict(row) for row in exact],
        "same_path": [_row_dict(row) for row in variants],
    }


@router.get("/diagnose-easycosmetic-variant-discovery")
def diagnose_easycosmetic_variant_discovery(
    max_pages: int = Query(120, ge=1, le=300),
    max_depth: int = Query(8, ge=0, le=12),
    max_events: int = Query(500, ge=50, le=2000),
):
    """
    Read-only Easycosmetic variant discovery diagnostic.

    The HTML trace makes HTTP requests to public retailer pages but does not
    run a production search, resync, ProductMatcher, catalog discovery worker,
    product hydration, or any database write.
    """
    started = time.monotonic()
    out = {
        "diagnostic": "easycosmetic-variant-discovery-read-only-v1",
        "ok": False,
        "read_only": True,
        "database_written": False,
        "production_search_called": False,
        "resync_called": False,
        "product_matcher_called": False,
        "catalog_discovery_worker_called": False,
        "hydration_called": False,
        "network_called": True,
        "store": "easycosmetic",
        "targets": TARGETS,
        "trace": None,
        "persistent_rows": {},
        "diagnosis": None,
    }

    try:
        import catalog_engine

        trace_fn = getattr(catalog_engine, "diagnose_html_discovery_trace", None)
        if not callable(trace_fn):
            out["error"] = "catalog_engine.diagnose_html_discovery_trace_unavailable"
            return out

        trace = trace_fn(
            "easycosmetic",
            query="Valentino Born In Roma Coral Fantasy",
            max_pages=max_pages,
            max_depth=max_depth,
            max_events=max_events,
        )
        out["trace"] = trace

        conn = catalog_engine.db()
        try:
            for name, target in TARGETS.items():
                url = target["url"]
                if not url:
                    out["persistent_rows"][name] = {
                        "note": "Exact target URL not configured; path-family rows still need manual review."
                    }
                    continue
                out["persistent_rows"][name] = {
                    "store_urls": _query_rows(conn, "store_urls", url),
                    "hydration_queue": _query_rows(conn, "hydration_queue", url),
                    "store_products": _query_rows(conn, "store_products", url),
                }
        finally:
            conn.close()

        found = []
        trace_urls = []
        if isinstance(trace, dict):
            for event in trace.get("events", []) or []:
                for item in event.get("query_relevant_links", []) or []:
                    trace_urls.append(item.get("url", ""))
            trace_urls.extend(item.get("url", "") for item in trace.get("query_url_hits", []) or [])
        normalized_trace_urls = {str(url).split("#", 1)[0].lower() for url in trace_urls if url}
        for name, target in TARGETS.items():
            url = target["url"]
            if url and url.split("#", 1)[0].lower() in normalized_trace_urls:
                found.append(name)

        out["trace_target_hits"] = found
        if not isinstance(trace, dict) or not trace.get("ok"):
            out["diagnosis"] = "TRACE_FAILED_OR_INCOMPLETE"
        elif found:
            out["diagnosis"] = "TRACE_FOUND_ONE_OR_MORE_TARGET_VARIANTS_CHECK_PERSISTENCE_ROWS"
        else:
            out["diagnosis"] = "TARGET_VARIANTS_NOT_VISIBLE_IN_RELEVANT_TRACE_EVENTS"
        out["ok"] = True
        return out

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    finally:
        out["elapsed_sec"] = round(time.monotonic() - started, 3)


if __name__ == "__main__":
    pass
