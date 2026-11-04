"""Configure and populate the optional Meilisearch catalog index.

Run from backend/: python scripts/reindex_meilisearch.py
"""
from app.search.meilisearch import configure_index, reindex_catalog


if __name__ == "__main__":
    configured = configure_index()
    if configured is None:
        raise SystemExit("MEILISEARCH_URL is not configured")
    print({"settings_task": configured, "result": reindex_catalog()})
