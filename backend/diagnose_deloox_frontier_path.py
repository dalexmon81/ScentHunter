from fastapi import APIRouter, Query
import time
import urllib.parse

router = APIRouter()

ATLANTIS_URL = "https://www.deloox.be/produit/1382469/rasasi-hawas-atlantis-eau-de-parfum-100-ml.html"
LA_MER_URL = "https://www.deloox.com/product/1405459/rasasi-hawas-la-mer-eau-de-parfum-100-ml.html"
BORN_GOLD_DONNA = "https://www.deloox.be/produit/1359240/valentino-born-in-roma-the-gold-donna-eau-de-parfum-100-ml.html"
BORN_GOLD_UOMO = "https://www.deloox.be/produit/1359237/valentino-born-in-roma-the-gold-uomo-eau-de-toilette-100-ml.html"
BORN_IVORY_DONNA = "https://www.deloox.be/produit/1400164/valentino-donna-born-in-roma-ivory-eau-de-parfum-limited-edition-100-ml.html"
BORN_IVORY_UOMO = "https://www.deloox.be/produit/1400167/valentino-born-in-roma-ivory-uomo-eau-de-toilette-limited-edition-100-ml.html"
BORN_TARGETS = {
    "gold_donna": BORN_GOLD_DONNA,
    "gold_uomo": BORN_GOLD_UOMO,
    "ivory_donna": BORN_IVORY_DONNA,
    "ivory_uomo": BORN_IVORY_UOMO,
}


def _row_dict(row):
    return dict(row) if row is not None else None


def _find_exact(conn, table, url):
    return conn.execute(
        f"SELECT * FROM {table} WHERE store=? AND url=? LIMIT 1",
        ("deloox", url),
    ).fetchone()


def _find_url_variants(conn, table, url):
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/")
    rows = conn.execute(
        f"""
        SELECT *
        FROM {table}
        WHERE store='deloox'
          AND (
              url=?
              OR lower(url)=lower(?)
              OR lower(url) LIKE ?
          )
        ORDER BY url
        LIMIT 20
        """,
        (url, url, f"%{path}"),
    ).fetchall()
    return [_row_dict(row) for row in rows]


def _queue_token_matches(conn, token_sets, limit=50):
    rows = conn.execute(
        """
        SELECT store,url,depth,priority,source,state,attempts,
               available_at,first_seen_at,last_started_at,last_finished_at,
               leased_until,last_error
        FROM catalog_discovery_queue
        WHERE store='deloox'
        ORDER BY priority ASC, depth ASC, url ASC
        """
    ).fetchall()

    result = []
    for row in rows:
        text = str(row["url"] or "").lower()
        matched = [token for token in token_sets if token in text]
        if len(matched) == len(token_sets):
            result.append(_row_dict(row))
            if len(result) >= limit:
                break
    return result


@router.get("/diagnose-deloox-frontier-path")
def diagnose_deloox_frontier_path(
    atlantis_url: str = Query(ATLANTIS_URL),
    la_mer_url: str = Query(LA_MER_URL),
    max_token_matches: int = Query(50, ge=1, le=200),
):
    """
    Strictly read-only SQLite diagnostic.

    It does NOT:
      - contact Deloox
      - run discovery
      - run a resync
      - run production search
      - run ProductMatcher
      - hydrate products
      - modify any database row

    It compares two already-proven Deloox product URLs:
      1) Hawas Atlantis: known to be exposed by Deloox but absent from catalog.
      2) Hawas La Mer: known to be present in the persistent catalog.

    The diagnostic checks both the durable discovery frontier and store_urls,
    then reports exact row state, depth, priority, source and errors.
    """
    started = time.monotonic()

    out = {
        "diagnostic": "deloox-frontier-path-read-only-v1",
        "ok": False,
        "read_only": True,
        "database_written": False,
        "network_called": False,
        "production_search_called": False,
        "product_matcher_called": False,
        "store": "deloox",
        "targets": {
            "atlantis": {
                "url": atlantis_url,
                "known_surface": "Deloox scraper/search previously discovered this URL",
            },
            "hawas_la_mer": {
                "url": la_mer_url,
                "known_surface": "Deloox URL previously persisted and verified in catalog",
            },
        },
        "frontier": {},
        "store_urls": {},
        "comparison": {},
    }

    try:
        from catalog_engine import db
        conn = db()

        try:
            for name, url in (
                ("atlantis", atlantis_url),
                ("hawas_la_mer", la_mer_url),
            ):
                out["frontier"][name] = {
                    "exact": _find_exact(conn, "catalog_discovery_queue", url),
                    "variants": _find_url_variants(conn, "catalog_discovery_queue", url),
                }
                out["store_urls"][name] = {
                    "exact": _find_exact(conn, "store_urls", url),
                    "variants": _find_url_variants(conn, "store_urls", url),
                }

            atlantis_tokens = ("rasasi", "hawas", "atlantis")
            la_mer_tokens = ("rasasi", "hawas", "la-mer")
            out["frontier"]["token_family_matches"] = {
                "atlantis": _queue_token_matches(conn, atlantis_tokens, max_token_matches),
                "hawas_la_mer": _queue_token_matches(conn, la_mer_tokens, max_token_matches),
            }

            state_rows = conn.execute(
                """
                SELECT state, COUNT(*) AS count
                FROM catalog_discovery_queue
                WHERE store='deloox'
                GROUP BY state
                ORDER BY state
                """
            ).fetchall()
            priority_rows = conn.execute(
                """
                SELECT priority, COUNT(*) AS count
                FROM catalog_discovery_queue
                WHERE store='deloox'
                GROUP BY priority
                ORDER BY priority
                LIMIT 30
                """
            ).fetchall()

            out["frontier"]["state_counts"] = {
                str(row["state"]): int(row["count"] or 0) for row in state_rows
            }
            out["frontier"]["priority_counts"] = [
                {"priority": int(row["priority"]), "count": int(row["count"] or 0)}
                for row in priority_rows
            ]

            a_frontier = out["frontier"]["atlantis"]["exact"]
            l_frontier = out["frontier"]["hawas_la_mer"]["exact"]
            a_store = out["store_urls"]["atlantis"]["exact"]
            l_store = out["store_urls"]["hawas_la_mer"]["exact"]

            if a_store:
                diagnosis = "ATLANTIS_ALREADY_IN_STORE_URLS"
            elif a_frontier:
                diagnosis = "ATLANTIS_IN_FRONTIER_NOT_PERSISTED_TO_STORE_URLS"
            else:
                diagnosis = "ATLANTIS_NOT_IN_PERSISTENT_FRONTIER"

            out["comparison"] = {
                "atlantis": {
                    "frontier_exact": bool(a_frontier),
                    "store_urls_exact": bool(a_store),
                    "frontier_state": a_frontier.get("state") if a_frontier else None,
                    "frontier_depth": a_frontier.get("depth") if a_frontier else None,
                    "frontier_priority": a_frontier.get("priority") if a_frontier else None,
                    "frontier_source": a_frontier.get("source") if a_frontier else None,
                    "frontier_attempts": a_frontier.get("attempts") if a_frontier else None,
                    "frontier_last_error": a_frontier.get("last_error") if a_frontier else None,
                },
                "hawas_la_mer": {
                    "frontier_exact": bool(l_frontier),
                    "store_urls_exact": bool(l_store),
                    "frontier_state": l_frontier.get("state") if l_frontier else None,
                    "frontier_depth": l_frontier.get("depth") if l_frontier else None,
                    "frontier_priority": l_frontier.get("priority") if l_frontier else None,
                    "frontier_source": l_frontier.get("source") if l_frontier else None,
                    "frontier_attempts": l_frontier.get("attempts") if l_frontier else None,
                    "frontier_last_error": l_frontier.get("last_error") if l_frontier else None,
                },
                "diagnosis": diagnosis,
            }

            out["ok"] = True
            return out
        finally:
            conn.close()

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    finally:
        out["elapsed_sec"] = round(time.monotonic() - started, 3)


@router.get("/diagnose-deloox-generic-search-coverage")
def diagnose_deloox_generic_search_coverage(
    max_results_per_query: int = Query(500, ge=1, le=2000),
):
    """
    READ-ONLY bridge diagnostic for the Deloox catalog-search handoff.

    This executes the SAME deployed Deloox scraper _discover() that the
    catalog_engine generic-search bridge imports, but it only inspects the
    returned URLs. It does not call catalog_engine._discover_deloox_catalog(),
    _deloox_persist_products(), hydration, ProductMatcher, production search,
    or any repair/resync endpoint.

    Purpose: determine whether the generic catalog terms currently configured
    in catalog_engine can actually reach the four Born in Roma products that
    the proven query-specific scraper path already finds.
    """
    started = time.monotonic()
    out = {
        "diagnostic": "deloox-generic-search-coverage-read-only-v1",
        "ok": False,
        "read_only": True,
        "database_written": False,
        "network_called": True,
        "production_search_called": False,
        "product_matcher_called": False,
        "catalog_discovery_called": False,
        "catalog_persist_called": False,
        "store": "deloox",
        "configured_generic_queries": [],
        "queries": [],
        "born_in_roma_targets": {
            name: {"url": url, "found_by_queries": []}
            for name, url in BORN_TARGETS.items()
        },
        "diagnosis": None,
    }

    session = None
    try:
        import catalog_engine
        from scrapers.deloox import scraper
        
        configured = tuple(getattr(catalog_engine, "DELOOX_GENERIC_CATALOG_QUERIES", ()) or ())
        discover = getattr(scraper, "_discover", None)
        headers = getattr(scraper, "HEADERS", {})

        out["configured_generic_queries"] = list(configured)
        out["catalog_engine_module"] = getattr(catalog_engine, "__file__", None)
        out["scraper_module"] = getattr(scraper, "__file__", None)
        out["scraper_discover_function"] = getattr(discover, "__name__", None)

        if not callable(discover):
            out["error"] = "deloox_scraper_discover_unavailable"
            return out

        session = __import__("requests").Session()
        session.headers.update(headers)

        for query in configured:
            query = str(query or "").strip()
            if not query:
                continue
            try:
                urls = list(discover(session, query) or [])
                urls = urls[:max_results_per_query]
                found_targets = []
                for name, target in BORN_TARGETS.items():
                    target_found = target in urls
                    if target_found:
                        out["born_in_roma_targets"][name]["found_by_queries"].append(query)
                        found_targets.append(name)
                out["queries"].append({
                    "query": query,
                    "candidate_count": len(urls),
                    "target_matches": found_targets,
                    "target_match_count": len(found_targets),
                    "target_urls": [u for u in urls if any(u == t for t in BORN_TARGETS.values())],
                })
            except Exception as exc:
                out["queries"].append({
                    "query": query,
                    "candidate_count": 0,
                    "target_matches": [],
                    "target_match_count": 0,
                    "error": f"{type(exc).__name__}: {exc}",
                })

        found_count = sum(
            1 for value in out["born_in_roma_targets"].values()
            if value["found_by_queries"]
        )

        if found_count == 4:
            out["diagnosis"] = "GENERIC_TERMS_REACH_ALL_BORN_IN_ROMA_TARGETS"
        elif found_count > 0:
            out["diagnosis"] = "GENERIC_TERMS_REACH_ONLY_SOME_BORN_IN_ROMA_TARGETS"
        else:
            out["diagnosis"] = "GENERIC_TERMS_DO_NOT_REACH_BORN_IN_ROMA_TARGETS"

        out["ok"] = True
        return out

    except Exception as exc:
        out["error"] = f"{type(exc).__name__}: {exc}"
        return out
    finally:
        if session is not None:
            session.close()
        out["elapsed_sec"] = round(time.monotonic() - started, 3)


if __name__ == "__main__":
    pass
