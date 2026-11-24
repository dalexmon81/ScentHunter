# Phase 1 — legacy dependency map (first pass)

**Branch:** `phase1-legacy-dependency-map-2026-11-24`  
**Scope:** static reference search on the current `main` tree; not a complete dynamic call graph.

## Decision
No legacy runtime file is safe to delete in this slice. The current PostgreSQL production entrypoint is separate from the old monolith, but the old modules are still imported by scripts, diagnostics, the Next Engine compatibility path and Notino feed utilities.

## Dependency map

| Legacy asset | Confirmed reference areas | Why it still matters | Safe next action |
|---|---|---|---|
| `backend/main.py` | Legacy FastAPI routes and diagnostics; legacy runtime entrypoint references | Contains compatibility endpoints and old catalog flows; not Fly's current entrypoint | Keep out of production startup; map external callers and tests before retirement |
| `backend/catalog_engine.py` | `backend/main.py`; `backend/catalog_family_coverage.py`; `backend/scenthunter_next_engine/runtime.py`; `catalog_url_hygiene.py`; `scrapers/notino/affiliate_feed.py`; scripts and diagnostics | Exposes legacy DB helpers, URL logic, parsers, discovery and search functions still called by other code | Extract pure functions and persistence dependencies behind tested interfaces; retain compatibility shim until references reach zero |
| `backend/product_matcher.py` | Legacy `main.py`, old search/matching flows and tests | Legacy product/family matching remains part of the compatibility surface | Add characterization fixtures and compare output with canonical PostgreSQL matching before replacement |
| `backend/product_catalog.json` | `backend/main.py`; `scenthunter_next_engine` repository/runtime/CLI; Notino fallback matcher; seed and backfill scripts; comparison tests | Still supplies canonical identities to fallback matching, import and audit tools | Preserve as immutable migration input; build a deterministic import/reconciliation report before any retirement |
| `backend/family_registry.json` | `backend/main.py`; `backend/catalog_family_coverage.py`; `product_matcher.py`; hydration tests and diagnostics | Supplements family aliases/variant resolution and remains a test fixture/source | Extract aliases into canonical DB with count/hash reconciliation; retain read-only compatibility until parity is proven |
| `backend/scrapers/*` | Legacy catalog engine, connector adapters, scripts and diagnostics | Parser functions are reused by newer connector adapters and operational diagnostics | Keep parser implementations; test each adapter independently before extracting or changing parser behavior |
| `backend/scrapers/notino/affiliate_feed.py` | `app/connectors/notino_feed.py`; `app/workers/notino_runtime.py`; import/bootstrap scripts; legacy catalog DB helpers | Authorized CJ/VIV XML remains current Notino ingestion source and still calls legacy DB helpers in utility paths | Separate feed transport/parser from old SQLite persistence; keep CJ feed active until direct Notino replacement passes full live acceptance |
| `backend/offer_engine/refresh_worker.py` | Legacy scheduled refresh configuration and scripts/workflows | Separate legacy refresh route; not the canonical production worker | Prove no active deployment/schedule references it; compare behavior with `app.services.offer_refresh` before disabling |
| `backend/phase0_baseline_worker.py` | Legacy Phase 0 workflow and old admin endpoints | Uses the old SQLite job flow and is not part of the current PostgreSQL production worker | Keep isolated; use PostgreSQL read-only audit reports for future baselines |

## Confirmed reference examples

- `backend/main.py` imports functions from `catalog_engine` for legacy catalog search and refresh paths.
- `backend/catalog_family_coverage.py` imports `_deloox_persist_products` and `_deloox_queue_allowed` from `catalog_engine`.
- `backend/scenthunter_next_engine/runtime.py` imports `catalog_engine` for shadow-search fallback behavior.
- `backend/scenthunter_next_engine/catalog_url_hygiene.py` imports `backend.catalog_engine`.
- `backend/scrapers/notino/affiliate_feed.py` imports `DB_PATH`, `db` and `_notino_variant_url` from `catalog_engine` in legacy helper paths.
- `backend/app/workers/notino_runtime.py` loads `product_catalog.json` as a conservative fallback matcher.
- `backend/scripts/ingest_notino_catalog.py`, `bootstrap_notino_postgres.py`, seed/backfill scripts and comparison tools still read `product_catalog.json`.
- `backend/catalog_family_coverage.py` reads `family_registry.json`; legacy matching and tests also consume it.
- Diagnostic utilities under `tools/diagnostics/` and `tools/debug/` import legacy functions. These tools are not automatically safe to delete: they preserve operational recovery knowledge and regression workflows.

## Completed Phase 1 domain extractions (current branch)

| Previous service path | Canonical implementation | Compatibility policy |
|---|---|---|
| `app.models.normalization` | `app.catalog.normalization` | Re-export shim; regression test asserts object identity |
| `app.services.canonical_matching` | `app.matching.canonical_matching` | Re-export shim; worker and test imports updated |
| `app.services.ingestion_persistence` | `app.offers.persistence` | Re-export shim; connector, Bplatz adapter, scripts and tests updated |
| `app.services.connector_ingestion` | `app.offers.ingestion` | Re-export shim; workers, scripts and tests updated |
| `app.services.offer_refresh` | `app.pricing.offer_refresh` | Re-export shim; workers and tests updated |
| `app.services.connector_health` | `app.monitoring.connector_health` | Re-export shim; workers, operator script and tests updated |
| `app.services.bplatz_phase2_adapter` | `app.offers.bplatz_adapter` | Re-export shim; catalog engine, live script and Bplatz tests updated |

The old paths above contain imports only; the implementation exists once in the new package. Keep these shims until all external or untracked consumers are ruled out.

## Additional discovery, extraction, repository and import-audit extractions (current branch)

- `app.discovery.dispatch` now owns the shared candidate-fetch dispatch and pagination continuation used by both Notino and legacy worker discovery handlers.
- Discovery candidates are not pre-filtered by retailer-specific or legacy matching logic; canonical resolution remains in `app.matching` and publication remains in `app.offers`.
- Isolated regression coverage: `backend/tests/test_discovery_dispatch.py`; the worker queue workflow runs this suite.
- `backend/scripts/audit_python_import_graph.py` now builds a read-only AST graph for tracked backend Python modules; CI runs its tests and uploads the graph artifact. The graph includes static imports only; dynamic imports and runtime plugin loading still require separate review.

## Current discovery and extraction boundaries\n\n- `app.discovery.dispatch` is the shared pagination/queue-dispatch policy used by both Notino and legacy retailer discovery handlers.\n- `app.extraction.product` is the shared known-product and price/stock fetch boundary used by both Notino and legacy retailer workers. It preserves raw fields; it does not parse, match or publish.\n- Retailer-specific transport and parsing remain in `app.connectors.notino_feed`, `app.connectors.legacy_scrapers` and `backend/scrapers/*`; no scraper code was copied or rewritten.\n- `app.repositories.ingestion_runs` owns transaction-scoped run persistence; the worker path is a compatibility re-export.\n\n## Proposed extraction sequence

1. [x] Create/retain characterization tests for normalization, canonical matching, connector contracts, worker behavior and discovery dispatch; additional retailer parser and legacy catalog persistence coverage remains in its existing suites.
2. [x] Move normalization/identity helpers into `app/catalog` and canonical matching into `app/matching`; keep old import paths as compatibility wrappers.
3. [ ] Move source-specific parsing into `app/connectors` only where the new adapter can call the exact existing parser; do not fork parser logic.
4. Separate Notino XML download/parse from legacy SQLite writes. Keep the authorized feed source in service until direct Notino discovery is proven for search, product detail, price, currency, availability and EAN.
5. [x] Move offer ingestion/persistence into `app/offers` and pricing refresh into `app/pricing` while preserving caller-owned database transaction boundaries.
6. Replace legacy scripts/workflows one at a time and record the replacement path.
7. Run repository-wide import/reference checks and the relevant test suites. Delete a legacy module only when references are zero, compatibility is unnecessary, and rollback is documented.

## Phase 1 exit criteria for dependency mapping

- [x] Existing target packages are documented in `docs/PHASE_1_STRUCTURE_MAP.md`.
- [x] First-pass references from legacy monolith, catalog, matcher, JSON registries, Notino feed and old workers are recorded.
- [ ] Review the generated static import graph artifact and reconcile any remaining legacy import edges (AST graph generator and CI artifact pipeline are now implemented).
- [ ] Add/verify characterization tests for every extracted responsibility (normalization, matching, offers, pricing, monitoring, discovery, extraction and ingestion-run repository tests now exist; final CI run is pending).
- [ ] Verify all legacy callers have a tested replacement before any module moves.

**Safety:** This document does not authorize deletion, data migration, feed removal, workflow disablement or production changes.
