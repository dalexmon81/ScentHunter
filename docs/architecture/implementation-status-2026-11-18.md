# ScentHunter catalog-first migration — implementation status

Audit date: 2026-11-18
Repository: `dalexmon81/ScentHunter`
Audited base: `main` at `defe49283754281c81f540fbdc3ef5588097c692`

This document records what is present in the audited `main` tree. A file, README, workflow reference, or isolated prototype is not treated as a completed production capability.

## Executive status

ScentHunter already contains a substantial catalog-first foundation, but the new canonical catalog is still an isolated pilot. The normal frontend path has not been switched to it. The current production search path and the canonical Phase 2 database are two separate systems.

## Verified implementation

- The legacy backend is still monolithic: `backend/main.py` is approximately 241 KB in the audited revision; `catalog_engine.py` and `product_matcher.py` remain in their original locations.
- The legacy persistent retailer catalog and its discovery/hydration loops remain the main application data path.
- `backend/app/` contains a canonical SQLAlchemy model, database setup, read-only catalog search API, search service, and an ingestion persistence service.
- Alembic migrations `0001_initial_catalog`, `0002_ingestion_raw`, and `0003_store_domain` exist in this tree.
- The canonical schema includes brands, fragrances, variants, stores, offers, price history, match audit, ingestion runs, raw ingestion, and explicit legacy-ID maps.
- The database layer supports SQLite and PostgreSQL via psycopg 3, but SQLite is still the default. PostgreSQL is not the active default deployment.
- A conservative persistence adapter exists for Bplatz. The canonical search API only returns promoted, fresh, in-stock, explicitly priced/currency-sourced offers with matching audit and store-domain checks.
- The canonical seed script is deliberately restricted to canonical identities/variants and the Bplatz store. It does not import retailer offers.
- A separate in-memory Next Engine contains normalization, canonical matching, and aggregation logic. It is opt-in and does not replace production search.
- The frontend has an explicit `?catalog_first=1` switch for the canonical pilot. Without it, the frontend calls `/search-start`.

## Verified gaps against the operating plan

| Plan area | Actual state in audited main | Status |
|---|---|---|
| Phase 0 — safety and baseline | Existing source catalog and family registry are tracked; baseline scripts exist, but a complete current metrics report and store-by-store connector inventory are not established by this audit | Partial |
| Phase 1 — repository cleanup | Diagnostics are outside the production package, but `main.py`, `catalog_engine.py`, and `product_matcher.py` remain monoliths; most new package directories contain README scaffolding only | Partial |
| Phase 2 — database | Canonical relational schema and migrations exist; SQLite remains default and production PostgreSQL cutover is not proven | Partial |
| Phase 3 — normalization | Normalizer exists inside the isolated Next Engine; it is not yet a shared, production ingestion service for every retailer | Partial |
| Phase 4 — universal connectors | `backend/app/connectors/` contains only README scaffolding; no shared StoreConnector contract or per-store connector implementations exist there | Missing |
| Phase 5 — ingestion queues | No Celery application/queue implementation is present in the audited main tree; the legacy refresh worker remains separate | Missing |
| Phase 6 — matching and validation | Canonical matcher and persistence/publication gate exist in isolated/pilot code; universal retailer-to-database matching is incomplete | Partial |
| Phase 7 — search | Canonical database search API exists, but the canonical query service is not Meilisearch/OpenSearch-backed and does not yet implement the planned full FTS/index/filter set | Partial |
| Phase 8 — ranking | Canonical search orders eligible offers by price; reliability/freshness/shipping/match scoring and price-trend ranking are not implemented as a complete service | Missing |
| Phase 9 — API and frontend | Canonical API exists as an opt-in pilot; default frontend still uses the legacy `/search-start` flow | Partial |
| Phase 10 — observability | Tests and status counts exist, but the complete admin console, alerting, and operational metrics are not implemented | Partial |
| Phase 11 — gradual migration | No evidence of controlled 5/20/50/100% traffic rollout to the canonical API | Not started |
| Phase 12 — scaling | No complete multi-store connector onboarding gate based on measured quality is implemented | Not started |

## Critical integration risks

1. **The frontend default is not the canonical database.** The normal UI calls `/search-start`; `?catalog_first=1` is required to use `/api/catalog/search`.
2. **The old and new catalogs are separate.** The existing legacy retailer catalog is still the main application source; the canonical database pilot is not yet a complete replacement.
3. **The requested Dior vertical slice is not complete.** The persisted canonical pilot currently centers on Bplatz / French Avenue Liquid Brun, not Dior Sauvage EDP 100 ml.
4. **The universal connector and Celery worker packages are absent from main.** Do not assume that references in old workflows mean the implementation exists.
5. **A staging worker workflow is stale after branch cleanup.** `.github/workflows/deploy-staging-worker.yml` checks out `phase5/fly-staging-workers-config`, a branch no longer present. It also references worker tests and migration revision `0007_ingestion_dead_letters` that are not in the audited main tree. Treat that workflow as non-runnable until reconciled.
6. **Do not switch the frontend default yet.** The canonical seed is Bplatz-scoped and the pilot does not yet have broad store coverage, complete ingestion automation, or the required operational rollback evidence.

## Safe implementation order from this baseline

1. Re-establish Phase 0 evidence on main: inventory the actual catalog, family registry, configured stores, current offers, and data-quality metrics. Keep the source files unchanged.
2. Complete the canonical schema and normalization contracts, then add migration and test coverage for any schema changes.
3. Implement a provider-neutral StoreConnector contract and adapt one structured retailer first.
4. Implement the ingestion pipeline and dead-letter/quarantine behavior, keeping workers isolated from HTTP requests.
5. Connect normalization, matching, validation, raw provenance, audit, and offer promotion as one tested pipeline.
6. Complete canonical search, then offer ranking and price history.
7. Complete the Dior Sauvage EDP 100 ml vertical slice with one retailer whose data access and product evidence are verified.
8. Run the new path in shadow mode, compare it against the existing path, and only then plan a guarded frontend cutover.

## Safety rules

- Do not delete or overwrite `product_catalog.json` or `family_registry.json`.
- Do not import guessed variants or publish offers without explicit stock, currency, URL, price, and a defensible canonical match.
- Do not run retailer network requests inside user-search handlers.
- Do not enable the canonical frontend path by default until coverage, freshness, matching quality, rollback, and production database identity are verified.
- Do not claim tests pass unless they have actually been executed in CI or a controlled local environment.
