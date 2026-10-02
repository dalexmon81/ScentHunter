from fastapi import APIRouter, Query
import time
import urllib.parse

router = APIRouter()

ATLANTIS_URL = "https://www.deloox.be/produit/1382469/rasasi-hawas-atlantis-eau-de-parfum-100-ml.html"
LA_MER_URL = "https://www.deloox.com/product/1405459/rasasi-hawas-la-mer-eau-de-parfum-100-ml.html"


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
            # Exact rows in the durable discovery frontier.
            for name, url in (
                ("atlantis", atlantis_url),
                ("hawas_la_mer", la_mer_url),
            ):
                out["frontier"][name] = {
                    "exact": _find_exact(conn, "catalog_discovery_queue", url),
                    "variants": _find_url_variants(
                        conn, "catalog_discovery_queue", url
                    ),
                }

                out["store_urls"][name] = {
                    "exact": _find_exact(conn, "store_urls", url),
                    "variants": _find_url_variants(conn, "store_urls", url),
                }

            # Generic token lookup over the frontier. This is NOT a product
            # rule; it is only a read-only way to see whether the structural
            # URL family exists anywhere in the persistent queue.
            atlantis_tokens = ("rasasi", "hawas", "atlantis")
            la_mer_tokens = ("rasasi", "hawas", "la-mer")

            out["frontier"]["token_family_matches"] = {
                "atlantis": _queue_token_matches(
                    conn, atlantis_tokens, max_token_matches
                ),
                "hawas_la_mer": _queue_token_matches(
                    conn, la_mer_tokens, max_token_matches
                ),
            }

            # Aggregate state counts make it clear whether the queue is merely
            # large or whether target-like URLs are actually represented.
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
                str(row["state"]): int(row["count"] or 0)
                for row in state_rows
            }
            out["frontier"]["priority_counts"] = [
                {
                    "priority": int(row["priority"]),
                    "count": int(row["count"] or 0),
                }
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
                    "frontier_state": (
                        a_frontier.get("state") if a_frontier else None
                    ),
                    "frontier_depth": (
                        a_frontier.get("depth") if a_frontier else None
                    ),
                    "frontier_priority": (
                        a_frontier.get("priority") if a_frontier else None
                    ),
                    "frontier_source": (
                        a_frontier.get("source") if a_frontier else None
                    ),
                    "frontier_attempts": (
                        a_frontier.get("attempts") if a_frontier else None
                    ),
                    "frontier_last_error": (
                        a_frontier.get("last_error") if a_frontier else None
                    ),
                },
                "hawas_la_mer": {
                    "frontier_exact": bool(l_frontier),
                    "store_urls_exact": bool(l_store),
                    "frontier_state": (
                        l_frontier.get("state") if l_frontier else None
                    ),
                    "frontier_depth": (
                        l_frontier.get("depth") if l_frontier else None
                    ),
                    "frontier_priority": (
                        l_frontier.get("priority") if l_frontier else None
                    ),
                    "frontier_source": (
                        l_frontier.get("source") if l_frontier else None
                    ),
                    "frontier_attempts": (
                        l_frontier.get("attempts") if l_frontier else None
                    ),
                    "frontier_last_error": (
                        l_frontier.get("last_error") if l_frontier else None
                    ),
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


if __name__ == "__main__":
    # This module is intended to be imported by FastAPI through main.py.
    # No standalone execution path performs network or database writes.
    pass
