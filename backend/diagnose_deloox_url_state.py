"""Strictly read-only diagnostic for the state of a single Deloox URL.

Opens SQLite with mode=ro (no schema creation, no writes), performs no
network calls and does not touch fast search, ProductMatcher, Family Registry
or the frontend.

CLI:  python diagnose_deloox_url_state.py "<url>"
API:  GET /diagnose-deloox-url-state?url=...
"""
import html
import json
import sqlite3
import sys
import urllib.parse

from fastapi import APIRouter, Query

router = APIRouter()

DEFAULT_URL = "https://www.deloox.be/chercher.html?q=parfum&amp;page=2"
STORE = "deloox"


def _rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _url_forms(url):
    """Raw, HTML-unescaped and host/trailing-slash variants of the URL."""
    forms = []
    for candidate in (url, html.unescape(url), html.unescape(html.unescape(url))):
        forms.append(candidate)
        forms.append(candidate.replace("&", "&amp;") if "&amp;" not in candidate else candidate)
    out = []
    for f in forms:
        if f not in out:
            out.append(f)
    return out


def _variant_rows(conn, table, forms):
    seen, result = set(), []
    parsed = urllib.parse.urlparse(forms[-1] if forms else "")
    path = parsed.path.rstrip("/")
    cond = " OR ".join(["url=?"] * len(forms))
    params = list(forms)
    sql = f"SELECT * FROM {table} WHERE store=? AND ({cond}"
    params = [STORE] + params
    if path:
        sql += " OR (lower(url) LIKE ? AND lower(url) LIKE ?)"
        params += [f"%{path.lower()}%", f"%{(parsed.query or '').lower()[:20]}%"]
    sql += ") ORDER BY url LIMIT 50"
    for row in _rows(conn, sql, params):
        if row["url"] not in seen:
            seen.add(row["url"])
            result.append(row)
    return result


def _exclusion_reasons(url, active):
    try:
        from catalog_engine import NON_PRODUCT_PATH, _looks_product
    except Exception as exc:  # pragma: no cover
        return [f"catalog_engine unavailable: {type(exc).__name__}: {exc}"], None
    reasons = []
    p = urllib.parse.urlparse(url)
    looks = bool(_looks_product(url, STORE))
    if p.scheme not in ("http", "https") or p.fragment:
        reasons.append("invalid scheme or has fragment")
    m = NON_PRODUCT_PATH.search(p.path)
    if m:
        reasons.append(
            f"path matches NON_PRODUCT_PATH ('{m.group(0).strip('/')}'): "
            "search/category/navigation page, not a product"
        )
    if "&amp;" in url:
        reasons.append("URL contains HTML-escaped '&amp;' (scraped from raw HTML, not unescaped)")
    if not looks:
        from catalog_engine import url_slug
        slug = url_slug(url)
        reasons.append(
            f"_looks_product() rejected URL: slug '{slug}' has {len(slug.split())} word(s), "
            "needs >=2 (generic product heuristic); query string is ignored"
        )
    if looks and not active:
        reasons.append("URL looks like a product but active=0; inactive for another reason")
    return reasons, looks


def diagnose(url=DEFAULT_URL):
    import catalog_engine
    out = {
        "diagnostic": "deloox-url-state-read-only-v1",
        "read_only": True,
        "database_written": False,
        "network_called": False,
        "url": url,
        "ok": False,
    }
    uri = f"file:{catalog_engine.DB_PATH}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only=1")
        forms = _url_forms(url)
        out["url_forms_checked"] = forms
        exact = _rows(
            conn, f"SELECT * FROM store_urls WHERE store=? AND url IN ({','.join('?' * len(forms))})",
            [STORE] + forms,
        )
        out["store_urls"] = exact
        out["store_urls_variants"] = _variant_rows(conn, "store_urls", forms)
        out["catalog_discovery_queue"] = _rows(
            conn, f"SELECT * FROM catalog_discovery_queue WHERE store=? AND url IN ({','.join('?' * len(forms))})",
            [STORE] + forms,
        )
        out["catalog_discovery_queue_variants"] = _variant_rows(conn, "catalog_discovery_queue", forms)
        urls = [r["url"] for r in exact] or forms
        ph = ",".join("?" * len(urls))
        out["store_products"] = _rows(
            conn, f"SELECT * FROM store_products WHERE store=? AND url IN ({ph})", [STORE] + urls)
        out["hydration_queue"] = _rows(
            conn, f"SELECT * FROM hydration_queue WHERE store=? AND url IN ({ph})", [STORE] + urls)
        active = bool(exact and exact[0].get("active"))
        reasons, looks = _exclusion_reasons(exact[0]["url"] if exact else url, active)
        out["active"] = exact[0]["active"] if exact else None
        out["discovered_at"] = exact[0]["discovered_at"] if exact else None
        out["looks_like_product"] = looks
        out["in_discovery_queue"] = bool(out["catalog_discovery_queue"])
        out["exclusion_reasons"] = reasons
        if not exact:
            out["diagnosis"] = "NOT_IN_STORE_URLS"
        elif active:
            out["diagnosis"] = "ACTIVE_IN_STORE_URLS"
        elif not looks:
            out["diagnosis"] = "INACTIVE_NON_PRODUCT_URL_EXCLUDED_FROM_PRODUCT_FRONTIER"
        else:
            out["diagnosis"] = "INACTIVE_UNKNOWN_REASON"
        out["ok"] = True
    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        conn.close()
    return out


@router.get("/diagnose-deloox-url-state")
def diagnose_deloox_url_state(url: str = Query(DEFAULT_URL)):
    return diagnose(url)


if __name__ == "__main__":
    print(json.dumps(diagnose(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL),
                     indent=2, default=str))
