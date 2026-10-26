# ScentHunter — Search Performance Baseline

This document records the known-good search configuration. Keep it updated when changing search behavior.

## Known-good code checkpoint

- Repository: https://github.com/dalexmon81/ScentHunter
- Baseline commit: `0ce4ace88756ca796ea34ba50426e7062f16488c`
- Commit URL: https://github.com/dalexmon81/ScentHunter/commit/0ce4ace88756ca796ea34ba50426e7062f16488c
- Date recorded: 2026-10-26

The baseline was confirmed by the user to return search results in under one second and show all expected variants for the broad query `Hawas`.

## Important implementation settings

### `backend/main.py` — `_catalog_search_terms(query)`

For a single-token query, keep the alias expansion limit at 32; for multi-token queries, keep it at 4:

```python
max_terms = 32 if len(query_tokens) <= 1 else 4
```

This avoids truncating the registered alias vocabulary for broad family searches such as `Hawas`, which previously used only 8 terms and omitted variants.

### `backend/catalog_engine.py` — stale-price repairs

In `_schedule_stale_price_repairs(rows, max_jobs=12)`, skip starting background stale-price repair jobs while a foreground search is running or within its idle grace period:

```python
if _foreground_search_running() or _foreground_search_idle_grace_active():
    return
```

This prevents background refresh work from competing with foreground search for SQLite locks, CPU, and network resources.

### `frontend/index.html` — status polling

Keep the 300 ms delay between non-completed `/search-status` polls to avoid tight polling that repeatedly processes offer snapshots.

### `backend/product_matcher.py` — family lookup cache

Keep a single `@lru_cache(maxsize=4096)` on `_family_for_query`; avoid duplicate stacked cache decorators.

## Change-safety rules

- Treat this as a known-good performance/recall baseline.
- Do not casually lower the single-token alias limit: it can hide legitimate family variants.
- Do not re-enable foreground-conflicting stale-price repair jobs without measuring their effect.
- Any search optimization must preserve both properties: sub-second perceived results and complete expected variant coverage.
- Before changing these paths, compare against this checkpoint and test broad one-token family searches (including `Hawas`) for latency and variant completeness.
- This file is a record, not a runtime configuration file. The actual behavior lives in the source files above.
