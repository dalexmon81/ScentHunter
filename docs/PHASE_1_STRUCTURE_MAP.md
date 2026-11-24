# Phase 1 — backend structure and responsibility map

**Branch:** `phase1-structure-foundation-2026-11-24`  
**Status:** additive scaffolding; no runtime cutover  
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
| `app/catalog` | Canonical brand, fragrance, variant and alias domain | `app/models/catalog.py`; `app/models/normalization.py` |
| `app/connectors` | Per-retailer transport and source parsing adapters | `app/connectors/base.py`; `legacy_scrapers.py`; `notino_feed.py`; `backend/scrapers/*` |
| `app/discovery` | Find retailer product candidates and persist discovery evidence | `app/services/connector_ingestion.py`; `app/workers/postgres_queue.py` |
| `app/extraction` | Fetch and parse a known retailer product page/feed record | `app/connectors/*`; `app/workers/notino_runtime.py` |
| `app/matching` | Resolve source records to canonical variants and audit uncertainty | `app/services/canonical_matching.py`; `app/models/catalog.py` |
| `app/offers` | Validate, stage and publish verified retailer offers | `app/services/connector_ingestion.py`; `app/services/ingestion_persistence.py` |
| `app/pricing` | Refresh prices, currency, stock and price history | `app/services/offer_refresh.py`; price-history model/repository |
| `app/workers` | Scheduling, durable queue execution, retries and orchestration | `app/workers/postgres_worker.py`; `postgres_queue.py`; `ingestion_run.py` |
| `app/repositories` | Database queries and persistence interfaces | Existing SQLAlchemy models and persistence services; extract incrementally |
| `app/models` | SQLAlchemy persistence models and shared persistence types | Existing `app/models/*` |
| `app/schemas` | Pydantic/API and internal data contracts | Existing schemas and connector contracts |
| `app/monitoring` | Health, connector status, ingestion metrics and diagnostics | `app/services/connector_health.py`; status route |
| `app/tests` | Domain-focused package-local tests where useful | Existing `backend/tests` remains canonical test-discovery root |

## Existing packages retained

The packages `api`, `config`, `connectors`, `matching`, `models`, `repositories`, `schemas`, `search`, `services` and `workers` already exist. Extend them; do not recreate them.

The additive target packages introduced in this branch are `catalog`, `discovery`, `extraction`, `offers`, `pricing`, `monitoring` and `tests`.

## Migration order

1. Add package boundaries and document ownership (this branch).
2. Map imports and call sites from `backend/main.py`, `catalog_engine.py`, `product_matcher.py`, `offer_engine` and legacy scripts.
3. Add characterization tests around existing behavior before moving implementation.
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

## Acceptance for this slice

- All target package paths exist.
- Each package has one documented responsibility and identifies existing code to reuse.
- Existing package locations are not duplicated.
- Production entrypoint and worker remain unchanged.
- No database, feed, scraper or production configuration is modified.
