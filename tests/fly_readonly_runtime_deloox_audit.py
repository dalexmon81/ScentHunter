"""Read-only production catalog audit, executed inside Fly.

The SQLite connection uses mode=ro and query_only=ON. This script contains
SELECT-only queries and must never enqueue, hydrate, update, or insert data.
"""
import json
import sqlite3
import time
import re
import urllib.request
from pathlib import Path

DB_PATH = Path("/data/store_catalog.sqlite3")
LIVE_SEARCH_URLS = (
    "https://www.deloox.nl/zoeken.html",
    "https://www.deloox.lu/chercher.html",
    "https://www.deloox.es/buscar.html",
    "https://www.deloox.com/search.html",
    "https://www.deloox.be/chercher.html",
)
TARGET_SEARCH_URLS = (
    "https://www.deloox.nl/zoeken.html",
    "https://www.deloox.lu/chercher.html",
    "https://www.deloox.es/buscar.html",
    "https://www.deloox.com/search.html",
    "https://www.deloox.be/chercher.html",
)

def is_deloox_product_url(url):
    """Mirror the catalog URL-admission contract without importing app code."""
    from urllib.parse import urlparse
    parsed = urlparse(str(url or ""))
    if parsed.scheme not in ("http", "https") or parsed.hostname is None:
        return False
    allowed_hosts = {
        "deloox.be", "www.deloox.be", "deloox.com", "www.deloox.com",
        "deloox.nl", "www.deloox.nl", "deloox.lu", "www.deloox.lu",
        "deloox.es", "www.deloox.es",
    }
    if parsed.hostname.lower().rstrip(".") not in allowed_hosts:
        return False
    path = (parsed.path or "/").lower()
    if re.search(r"/(?:product|produit|producto|prodotto)/\\d+(?:/|$)", path, re.I):
        return True
    route_path = re.sub(r"\\.(?:html?|php)$", "", path, flags=re.I)
    if path.endswith(".html") and not re.search(
        r"/(?:category|categorie|categoria|catégorie|chercher|zoeken|buscar|"
        r"search|suche|suchen|sitemap|brand|marque|marca|login|account|"
        r"cart|checkout)(?:/|$)",
        route_path,
        re.I,
    ):
        return True
    return False


def main():
    report = {
        "read_only": True,
        "database_mutated": False,
        "database_path": str(DB_PATH),
        "generated_at_epoch": time.time(),
        "live_search_url_probes": [],

        "tables": {},
        "invalid_search_url_rows": [],
        "invalid_active_deloox_url_rows": [],
        "active_deloox_url_rows_examined": 0,
        "parser_errors_by_day": [],
        "recent_parser_errors": [],
        "hydration_queue_states": [],
        "catalog_coverage_profondo": [],
    }

    # Fetch each endpoint with a small bounded timeout; this is HTTP GET only.
    # Do not follow beyond the final redirect target or process the page as a product.
    for url in LIVE_SEARCH_URLS:
        item = {"url": url}
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ScentHunterReadOnlyAudit/1.0)"},
        )
        try:
            with urllib.request.urlopen(request, timeout=7) as response:
                body = response.read(300_000)
                item.update({
                    "http_status": getattr(response, "status", None),
                    "final_url": response.geturl(),
                    "bytes_sampled": len(body),
                    "sample_truncated": len(body) >= 300_000,
                    "has_product_jsonld": bool(
                        re.search(r'"@type"\s*:\s*"(?:Product|ProductGroup)"', body.decode("utf-8", "replace"), re.I)
                    ),
                    "has_h1": bool(re.search(r"<h1\b", body.decode("utf-8", "replace"), re.I)),
                })
        except Exception as exc:
            item["http_error"] = type(exc).__name__ + ": " + str(exc)[:180]
        report["live_search_url_probes"].append(item)

    uri = "file:" + str(DB_PATH) + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    try:
        for table in ("store_urls", "store_products", "store_product_variants",
                      "store_url_metadata", "hydration_queue", "catalog_coverage"):
            try:
                columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
                if not columns:
                    report["tables"][table] = {"present": False}
                    continue
                info = {"present": True, "columns": sorted(columns)}
                if "store" in columns:
                    info["deloox_count"] = conn.execute(
                        f'SELECT COUNT(*) FROM "{table}" WHERE lower(store)=?',
                        ("deloox",),
                    ).fetchone()[0]
                if table == "store_products" and {"store", "fetch_status", "fetched_at"} <= columns:
                    info["parser_error_rows"] = conn.execute(
                        "SELECT COUNT(*) FROM store_products WHERE lower(store)=? "
                        "AND fetch_status LIKE '%product_parser_not_found%'",
                        ("deloox",),
                    ).fetchone()[0]
                    info["parser_errors_by_day"] = [
                        dict(row) for row in conn.execute(
                            "SELECT date(fetched_at,'unixepoch') AS day, COUNT(*) AS count "
                            "FROM store_products WHERE lower(store)=? "
                            "AND fetch_status LIKE '%product_parser_not_found%' "
                            "GROUP BY day ORDER BY day DESC LIMIT 10",
                            ("deloox",),
                        )
                    ]
                    info["recent_parser_errors"] = [
                        dict(row) for row in conn.execute(
                            "SELECT url, substr(fetch_status,1,240) AS error, fetched_at "
                            "FROM store_products WHERE lower(store)=? "
                            "AND fetch_status LIKE '%product_parser_not_found%' "
                            "ORDER BY fetched_at DESC LIMIT 12",
                            ("deloox",),
                        )
                    ]
                if table == "hydration_queue" and {"store", "state"} <= columns:
                    info["queue_states"] = [
                        dict(row) for row in conn.execute(
                            "SELECT state, COUNT(*) AS count FROM hydration_queue "
                            "WHERE lower(store)=? GROUP BY state ORDER BY state",
                            ("deloox",),
                        )
                    ]
                report["tables"][table] = info
            except Exception as exc:
                report["tables"][table] = {"query_error": type(exc).__name__ + ": " + str(exc)[:180]}

        # Audit the complete active Deloox URL set against the same generic
        # path contract used by catalog discovery. Read-only SELECT only.
        url_columns = {row["name"] for row in conn.execute("PRAGMA table_info(store_urls)")}
        if {"store", "url", "active"} <= url_columns:
            active_rows = conn.execute(
                "SELECT url FROM store_urls WHERE lower(store)=? AND active=1",
                ("deloox",),
            ).fetchall()
            report["active_deloox_url_rows_examined"] = len(active_rows)
            for row in active_rows:
                url = row["url"]
                if not is_deloox_product_url(url):
                    report["invalid_active_deloox_url_rows"].append({
                        "url": url,
                        "reason": "rejected_by_current_product_url_admission",
                    })

        for table in ("store_urls", "store_products"):
            columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
            if {"store", "url"} <= columns:
                for url in TARGET_SEARCH_URLS:
                    try:
                        rows = [dict(row) for row in conn.execute(
                            f'SELECT * FROM "{table}" WHERE lower(store)=? AND url=? LIMIT 2',
                            ("deloox", url),
                        )]
                        if rows:
                            report["invalid_search_url_rows"].append({"table": table, "url": url, "rows": rows})
                    except Exception as exc:
                        report["invalid_search_url_rows"].append(
                            {"table": table, "url": url, "query_error": type(exc).__name__ + ": " + str(exc)[:180]}
                        )

        coverage_columns = {row["name"] for row in conn.execute("PRAGMA table_info(catalog_coverage)")}
        if {"store", "canonical_name", "query", "state"} <= coverage_columns:
            report["catalog_coverage_profondo"] = [
                dict(row) for row in conn.execute(
                    "SELECT store, product_id, canonical_name, query, state, found_urls, last_error "
                    "FROM catalog_coverage WHERE lower(canonical_name) LIKE ? "
                    "OR lower(query) LIKE ? ORDER BY store, product_id LIMIT 20",
                    ("%acqua di gio%", "%profondo%"),
                )
            ]
    finally:
        conn.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, default=str))

if __name__ == "__main__":
    main()
