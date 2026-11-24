# Phase 1 — backend structure and responsibility map

**Implementation branch:** `phase1-catalog-boundary-tests-2026-11-24`  
**Status:** controlled catalog, matching, offers, pricing, monitoring, discovery-dispatch and ingestion-run repository extractions; static import-graph audit added; no production cutover  
**Production runtime:** `backend/postgres_main.py` + `backend/app/workers/postgres_worker.py`

## Rules

1. PostgreSQL remains the canonical source of truth.
2. User search is read-only and never calls retailer websites.
3. Retailer network I/O belongs in background connectors/workers.
4. Business logic belongs in domain modules/services, not FastAPI routers.
5. SQLAlchemy access belongs in repositories or narrowly scoped persistence services.
6. Every ingestion result retains source evidence and timestamps.
7. No legacy module, JSON catalog, feed parser, workflow, volume or database row is deleted in Phase 1.
8. New modules reuse existing models, schemas, connectors and services; no parallel matching, ingestion or offer-publication implementation.

## Target package ownership

| Package | Responsibility | Existing implementation to reuse |
|---|---|---|
| `app/api` | HTTP routes, request/response validation, auth boundary | `app/api/catalog_search.py`; `postgres_main.py` |
| `app/catalog` | Canonical brand, fragrance, variant and alias domain | `app/catalog/normalization.py` (single implementation); `app/models/catalog.py` (ORM persistence); legacy normalization re-export only |
| `app/connectors` | Per-retailer transport and source parsing adapters | `app/connectors/base.py`; `legacy_scrapers.py`; `notino_feed.py`; `backend/scrapers/*` |
| `app/discovery` | Dispatch every discovered reference to background fetch jobs and continue pagination | `app/discovery/dispatch.py`; retailer discovery I/O remains in connectors; worker owns queue backend and run accounting |
| `app/extraction` | Boundary for fetching a known retailer reference and preserving raw source evidence | Existing transport/parsing stays in `app.connectors`; worker invokes it; offer ingestion persists the raw record |
| `app/matching` | Resolve source records to canonical variants and audit uncertainty | `app/matching/canonical_matching.py` (single implementation); `app/models/catalog.py`; offer persistence records match audit |
| `app/offers` | Orchestrate extracted records, persist match outcomes and publish verified offers | `app/offers/ingestion.py` and `app/offers/persistence.py` (single implementations); old service paths are re-exports |
| `app/pricing` | Refresh price and availability for existing offers and append price history | `app/pricing/offer_refresh.py` (single implementation); old service path is a re-export |
| `app/workers` | Scheduling, durable queue execution, retries and orchestration | `app/workers/postgres_worker.py`; `postgres_queue.py`; `ingestion_run.py` |
| `app/repositories` | Transaction-scoped persistence operations and database query interfaces | `app/repositories/ingestion_runs.py`; `app.models` entities; offers/pricing keep their atomic domain persistence gates |
| `app/models` | SQLAlchemy persistence models and shared persistence types | Existing `app/models/*` |
| `app/schemas` | Pydantic/API and internal data contracts | Existing schemas and connector contracts |
| `app/monitoring` | Connector health, failure streaks, quarantine and recovery | `app/monitoring/connector_health.py` (single implementation); old service path is a re-export |
| `app/tests` | Domain-focused package-local tests where useful | Existing `backend/tests` remains canonical test-discovery root |

## Existing packages retained

The packages `api`, `config`, `connectors`, `matching`, `models`, `repositories`, `schemas`, `search`, `services` and `workers` already exist. Explicit package initializers are now present for `api`, `workers`, `repositories` and `schemas`; extend these packages rather than recreating them.

The additive target packages introduced in this branch are `catalog`, `discovery`, `extraction`, `offers`, `pricing`, `monitoring` and `tests`.

## Migration order

1. Add package boundaries and document ownership (this branch).
2. Map imports and call sites from `backend/main.py`, `catalog_engine.py`, `product_matcher.py`, `offer_engine` and legacy scripts.
3. Add characterization tests around existing behavior before moving implementation; CI runs discovery-dispatch and import-graph auditor tests.
4. Extract one responsibility at a time behind existing imports/API contracts.
5. Update runtime imports only after tests prove behavior parity.
6. Retire legacy paths only after repository-wide reference search, live connector acceptance and rollback review.

## Explicit non-goals

- No broad file moves or renames.
- No FastAPI route behavior changes.
- No database schema/migration changes.
- No new scheduler or queue implementation.
- No CJ/VIV removal; it remains a current Notino ingestion source.
- No Fly.io deployment or production secret changes.

## Acceptance for the current implementation slice

- All target package paths exist and have documented ownership.
- Catalog normalization, matching, offers, pricing and connector health each have one implementation; legacy import paths are re-export shims.
- Notino and legacy discovery workers share one tested dispatch/pagination implementation.
- CI builds a read-only AST import graph and uploads it as a workflow artifact; dynamic imports still require manual review.
- Production entrypoint, queue backend, database schema/data, feed, scrapers and production configuration remain unchanged.
