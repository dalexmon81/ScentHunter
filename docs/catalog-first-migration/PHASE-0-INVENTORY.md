# Phase 0 — repository inventory

**Snapshot date:** 2026-11-18  
**Repository:** `dalexmon81/ScentHunter`  
**Working branch:** `refactor/catalog-first-architecture`  
**Protected production branch:** `main`

This inventory is based on the tracked Git tree. Runtime database contents and production-mounted volumes are not accessible from a Git tree scan and are therefore not represented as live offer counts.

## Core code and migration inputs

| Path | Tracked size | Notes |
|---|---:|---|
| `backend/main.py` | 241,075 bytes | Legacy API/application entrypoint; must remain operational during migration |
| `backend/catalog_engine.py` | 337,477 bytes | Persistent catalog/search/discovery logic |
| `backend/product_matcher.py` | 140,062 bytes | Legacy matching implementation |
| `backend/product_catalog.json` | 1,242,247 bytes | Legacy catalog seed/input; preserve |
| `backend/family_registry.json` | 23,653 bytes | Family metadata; preserve |
| `backend/offer_engine/refresh_worker.py` | present | Legacy refresh worker; inspect before replacing |
| `backend/phase0_baseline_worker.py` | present | Durable Phase 0 worker |
| `backend/requirements.txt` | present | Backend dependencies |

## Existing catalog-first / database components

- `backend/app/`: API, config, connectors, DB, matching, models, repositories, schemas, search, services and workers packages.
- `backend/alembic/`: `0001_initial_catalog_schema.py`, `0002_ingestion_raw.py`, `0003_store_domain.py`.
- `backend/scenthunter_next_engine/`: canonical matcher, catalog repository, catalog migration/preflight/audit, offer normalizer/aggregator, runtime, Phase 0 baseline jobs and reports.
- SQLAlchemy models include brands, fragrances, variants, stores, offers, price history, match audit, ingestion raw payloads, ingestion runs and legacy ID maps.
- Existing Phase 0 workflow: `.github/workflows/phase-0-live-baseline.yml`.

## Store connectors present

| Store | Package |
|---|---|
| Bplatz | `backend/scrapers/bplatz/` |
| Deloox | `backend/scrapers/deloox/` |
| Easycosmetic | `backend/scrapers/easycosmetic/` |
| Notino | `backend/scrapers/notino/` |
| Orioudh | `backend/scrapers/orioudh/` |
| Parfumcity | `backend/scrapers/parfumcity/` |
| Parfumzentrum | `backend/scrapers/parfumzentrum/` |
| Perfumemarket | `backend/scrapers/perfumemarket/` |
| Sabina | `backend/scrapers/sabina/` |

Presence of a connector package does not prove current production health or successful ingestion. Those values must come from the Phase 0 runtime baseline.

## Diagnostics / debug

Diagnostic utilities already exist under `tools/diagnostics/` and debug helpers under `tools/debug/`. Preserve them for now. Several are coupled to legacy routes, tests, workflows or manual operational procedures. A later cleanup must inventory all references and retire only after the replacements exist.

## Baseline limitations and next data collection

The repository contains a read-only baseline generator at `backend/scenthunter_next_engine/baseline_report.py` and durable Phase 0 job workflow. It reads the local SQLite retailer catalog and canonical JSON catalog. This Git integration cannot access the production volume or execute the workflow with production secrets. Therefore the current live counts and percentages are **not yet measured here**.

Run the existing Phase 0 workflow in the intended production/staging environment, validate that its output is from the expected nine-store scope, and preserve the CSV as a workflow artifact. Do not fabricate zero values when the database/volume is inaccessible.

Required baseline fields:
- canonical product and variant counts;
- offers per store;
- valid positive price and ISO currency percentage;
- valid HTTP(S) product URL percentage;
- explicit recognized availability percentage;
- matched, ambiguous and unresolved counts;
- freshness distribution (e.g. under 1 hour, 1–6 hours, 6–24 hours, over 24 hours);
- store-level success/error/quarantine state and last successful sync.

## Phase 0 exit criteria

- [x] Confirm protected `main` and separate working branch.
- [x] Record tracked core-file sizes and connector inventory.
- [x] Identify existing schema, migration and Phase 0 code to reuse.
- [x] Confirm diagnostics are already isolated from `backend/`.
- [ ] Export production/staging live baseline CSV.
- [ ] Preserve a verified copy of production catalog/config/DB data with restore instructions.
- [ ] Document actual endpoint/feed fields and known issues for each store from connector code and runtime evidence.
- [ ] Approve Phase 1 dependency/import plan before moving code.
