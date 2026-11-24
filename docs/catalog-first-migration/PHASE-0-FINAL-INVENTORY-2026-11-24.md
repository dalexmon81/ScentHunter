# ScentHunter — Phase 0 current-state inventory

**Audit date:** 2026-11-24  
**Audited Git revision:** `main` at `5acbcb5cc4de8c36503c6c089fc9b41ca475cf4f`  
**Operational Neon project:** `square-math-01119225`  
**Operational Neon branch inspected:** `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`)  
**Scope:** read-only repository, workflow, Neon schema/data and deployment-evidence review. No source deletion, database cleanup, merge or deployment was performed for this report.

## Executive result

**Phase 0 is documented, but its exit gate is NOT passed.** The current code and database inventory is substantially complete. Three operational acceptance items remain blocked by unavailable Fly.io machine/volume access, the incompatible legacy Phase 0 baseline workflow, and the lack of a verified restore drill.

The most important findings are:

1. The public Fly app is configured to run `backend/postgres_main.py`; the worker is `backend/app/workers/postgres_worker.py`. The public frontend calls `/api/catalog/search`. The old monolithic `backend/main.py` is still tracked, but it is not the app entrypoint in `fly.toml`.
2. The current Postgres registry has 10 store rows, of which 6 are active and 4 inactive Deloox country storefronts. The original Phase 0 baseline scope expects 9 retailer identities. Three expected retailers (Orioudh, Parfumcity, PerfumeMarket) have scraper packages but no store row in the inspected Postgres registry.
3. The operational database contains 163 active offers. Deloox.be and Easycosmetic.de currently have zero active offers.
4. There are 73,763 queued jobs. **Every queued job is older than the worker's configured `SCENTHUNTER_QUEUE_MIN_CREATED_AT=2026-11-23T08:27:00Z` cutoff.** These jobs are therefore outside the worker's eligible time window. They were not altered during this audit.
5. Eighteen ingestion runs remain in `running` state; their start times range from 2026-11-22 04:19 UTC to 2026-11-23 23:03 UTC.
6. Notino's CJ/VIV XML feed is still a live dependency of the PostgreSQL ingestion path. A recent parser diagnostic accepted 77,015 feed offers and validated 77,013 CJ click destinations. The latest production feed monitor failed because it calls the obsolete `/catalog-status` route, which returns 404 on the current PostgreSQL-only app.
7. A recent Fly deployment completed its deploy step and passed health/catalog readiness, but its public-search smoke check failed because the test query `Dior Sauvage` returned zero publishable offers.
8. Git and Neon data copies exist and were read-verified, but no complete restore drill has been executed. The Neon backup branch cannot be protected because the plan's protected-branch limit has been reached.

## 1. Change freeze and GitHub state

- `main` is reported as protected by GitHub.
- Audited `main` SHA: `5acbcb5cc4de8c36503c6c089fc9b41ca475cf4f`.
- The repository tree contains 389 entries; the recursive tree response was not truncated.
- There are 15 open pull requests at the time of the audit. Work is not globally frozen; multiple work branches and PRs remain open.
- Deloox-only change is isolated in draft PR #903. Its latest head is `f9e30da02fca71b03fdc5bdb31aa0b562ae4fd81`; all five associated checks passed: backend parser regression, hydration regression, Next Engine shadow integration, catalog worker queue foundation and retailer connector contract. PR #903 is not merged.
- The Deloox-only change removes mappings for `deloox-com`, `deloox-lu`, `deloox-nl` and `deloox-es`, and limits the scraper host list to Deloox Belgium. On audited `main`, those old mappings are still present. In the operational DB, those four store rows are inactive. Do not reactivate them until the code/configuration alignment is resolved.

No merge, source deletion, or deployment was made as part of this Phase 0 inventory.

## 2. Git backup

Created branch:

- `phase0-git-snapshot-2026-11-24`
- Exact starting SHA: `5acbcb5cc4de8c36503c6c089fc9b41ca475cf4f`

This is an exact Git reference to the audited `main` revision. It is separate from the older `phase0-backup-2026-11-24` branch, which is two commits behind the audited `main` SHA.

The inventory report itself is being added on a separate documentation branch; neither branch changes `main`.

## 3. Runtime architecture and frontend

### Fly configuration tracked in Git

`fly.toml` declares:

- App: `scenthunter`
- Primary region: `ams`
- HTTP app process: `uvicorn postgres_main:app`
- Worker process: `python -m app.workers.postgres_worker`
- Queue backend: PostgreSQL
- `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL=1`
- Queue minimum creation timestamp: `2026-11-23T08:27:00Z`
- Release command runs Alembic migrations.

`fly.staging.toml` is a separate pilot app, `scenthunter-pilot-20261030`, using SQLite and a mounted `/data` volume. It is not the production Fly app configuration.

### Current public API and frontend

- `backend/postgres_main.py` is a small PostgreSQL-only FastAPI entrypoint. It mounts the catalog search router and serves `frontend/index.html`.
- `backend/app/api/catalog_search.py` exposes `/api/catalog/search` and `/api/catalog/status`.
- The current `frontend/index.html` calls `/api/catalog/search` directly. It does not contain the old `/search-start` call or the `catalog_first` opt-in switch.
- `backend/main.py` remains a large legacy application and still contains `/search-start`, old catalog-engine imports and retailer-search code. It is not the app entrypoint specified by current `fly.toml`, but remains a dependency of legacy scripts, tests and compatibility paths.
- `backend/app/search/catalog.py` performs database-only search and imports CJ URL validation for Notino attribution.

### Deployment evidence

The GitHub Actions Fly deployment run `45332439063` shows:

- Fly deploy step: success.
- Canonical PostgreSQL seed/store verification: success.
- Production health and catalog readiness: success.
- Public search verification: failure — `/api/catalog/search?q=Dior Sauvage` returned no publishable offers.

An earlier deployment run `45324835107` passed health, public-search parity, Bplatz refresh, daily discovery and Deloox URL requeue checks. The later failed smoke check must remain visible as an unresolved acceptance issue.

This GitHub evidence does not replace a direct Fly machine/volume inventory. No Fly.io account connector or GitHub Actions dispatch action is available in this audit session, so exact machine IDs/counts, attached volume contents, runtime secret names and current machine allocation could not be independently enumerated. An existing safe manual workflow is already present at `.github/workflows/scenthunter-readonly-fly-diagnostics.yml` (Actions name: **ScentHunter 2.0 read-only Fly diagnostics**). It reads app status, machine list, volume list, secret names only, runtime database backend/driver and SQLite file-presence markers; it explicitly performs no deploy, restart, migration, import, secret update or database write. This workflow should be manually dispatched to close the Fly inventory. Secret values must not be copied into the report.

## 4. Neon database inventory

### Branches and backup

The project is `Scenthunter` (`square-math-01119225`).

The operational database reviewed is `scenthunter_offerfirst` on branch `offer-first-postgres-cutover` (`br-red-night-ba3reqhp`). The project's default branch is named `production`, but the inspected `scenthunter_offerfirst` database was not present on that default branch. Therefore the branch name `production` must not be used as proof that this is the active app database.

A readable backup child branch exists:

- `phase0-verified-backup-2026-11-24-compute`
- ID: `br-odd-heart-bale2lvj`
- Parent: `offer-first-postgres-cutover`
- State: ready
- Read-only count verification succeeded.

Backup branch counts at its captured point:

| Object | Count |
|---|---:|
| brands | 65 |
| fragrances | 1,403 |
| product_variants | 556 |
| stores | 10 |
| offers | 163 |
| price_history | 8,582 |
| ingestion_runs | 50,128 |
| ingestion_raw | 48,100 |
| ingestion_queue_jobs | 173,039 |

The live operational branch continued changing after that copy. At the later audit query, its counts were:

| Object | Count |
|---|---:|
| brands | 65 |
| fragrances | 1,403 |
| product_variants | 556 |
| stores | 10 |
| offers | 163 |
| price_history | 8,739 |
| ingestion_runs | 50,291 |
| ingestion_raw | 48,257 |
| ingestion_queue_jobs | 173,202 |

The backup branch is ready and queryable, but it is not protected: Neon rejected a protection change because the account reached its maximum number of protected branches. A manual Neon snapshot named `scenthunter-phase0-before-cleanup-2026-11-24` exists, but its source is the default `production` branch, not the operational `offer-first-postgres-cutover` branch. Do not treat that snapshot as the backup of the operational offer-first database. Neon also rejected creation of a snapshot directly from the non-root operational branch. No branch was deleted.

### Current store registry and offers

| Store slug | DB status | Active offers | Ingestion runs |
|---|---|---:|---:|
| bplatz | active | 28 | 1,642 |
| deloox-be | active | 0 | 1,386 |
| deloox-com | inactive | 0 | 89 |
| deloox-es | inactive | 0 | 31 |
| deloox-lu | inactive | 0 | 48 |
| deloox-nl | inactive | 0 | 30 |
| easycosmetic-de | active | 0 | 2,842 |
| notino-fr | active | 108 | 41,055 |
| parfumzentrum-de | active | 6 | 1,836 |
| sabina-es | active | 21 | 1,332 |

There are six active store rows and four inactive Deloox market rows. The active offers total 163. The oldest active offer timestamp was 2026-11-23 09:34 UTC; the newest was 2026-11-24 06:25 UTC.

### Queue and run health

Queue totals:

| Queue status | Jobs |
|---|---:|
| completed | 48,201 |
| failed | 51,238 |
| queued | 73,763 |
| running | 0 |

All 73,763 queued jobs were created before the `fly.toml` worker cutoff of 2026-11-23 08:27 UTC. By store, queued jobs are:

| Store | Queued jobs |
|---|---:|
| bplatz | 2,816 |
| deloox-be | 15,342 |
| easycosmetic-de | 31,970 |
| notino-fr | 1,562 |
| parfumzentrum-de | 17,873 |
| sabina-es | 4,200 |

The four inactive Deloox international stores have zero queued jobs; their old jobs are retained as failed with an explicit deactivation reason. No historical rows were deleted.

There are 18 ingestion runs still marked `running`, with start timestamps from 2026-11-22 04:19 UTC to 2026-11-23 23:03 UTC. These should be reconciled in a separate approved operational task; this audit did not update them.

## 5. Old-system dependencies and module classification

### Large legacy inputs and modules

| Path | Tracked size | Classification |
|---|---:|---|
| `backend/main.py` | 229,536 bytes | Legacy API/search entrypoint; not Fly's current web entrypoint, but still referenced |
| `backend/catalog_engine.py` | 339,072 bytes | Legacy catalog, search, discovery and feed-status logic |
| `backend/product_matcher.py` | 140,062 bytes | Legacy identity matcher; compatibility/tests/scripts still reference it |
| `backend/product_catalog.json` | 1,244,924 bytes | Legacy catalog input and fallback matcher data; preserve |
| `backend/family_registry.json` | 23,653 bytes | Legacy family metadata; preserve |
| `backend/offer_engine/refresh_worker.py` | 6,814 bytes | Separate SQLite/legacy refresh worker; disabled unless explicitly enabled |
| `backend/phase0_baseline_worker.py` | 5,007 bytes | Phase 0 baseline worker using the legacy SQLite job implementation |
| `backend/app/workers/postgres_worker.py` | 6,301 bytes | Current PostgreSQL queue worker |
| `frontend/index.html` | 917,721 bytes | Current public UI |

### Reuse

- `backend/app/models/` and the PostgreSQL schema.
- Alembic migrations through `0006_postgres_ingestion_queue`.
- `backend/app/api/catalog_search.py` and `backend/app/search/catalog.py`.
- Shared connector contract in `backend/app/connectors/base.py`.
- Canonical matching and persistence services under `backend/app/services/`.
- PostgreSQL queue, ingestion-run tracking, raw evidence and price history.

### Modify or isolate before retirement

- `backend/main.py`, `backend/catalog_engine.py`, `backend/product_matcher.py`.
- Legacy SQLite catalog and refresh procedures.
- Notino public fallback and CJ feed monitor/diagnostic workflows.
- The Phase 0 SQLite baseline workflow and worker.
- Old Deloox multi-country mappings on `main`.
- Scripts that import the monolith or read `product_catalog.json`.

### Preserve for now

- `backend/product_catalog.json` and `backend/family_registry.json`.
- All scraper packages and diagnostic tools.
- Existing workflow YAML and historical data.
- `legacy_product_id_map` and `legacy_variant_id_map` tables.
- Ingestion raw payloads, runs, queue history and price history.

No code or data was deleted during this audit.

## 6. Retailer scraper inventory

Nine retailer scraper packages are tracked:

| Retailer | Package | Search/page parser in source | PostgreSQL connector wiring |
|---|---|---|---|
| Bplatz | `backend/scrapers/bplatz/` | `search_stream`, `extract_product_page` | Yes |
| Deloox | `backend/scrapers/deloox/` | `search_stream`, `extract_product_page` | Yes |
| Easycosmetic | `backend/scrapers/easycosmetic/` | `search_stream`, `extract_product_page` | Yes |
| Notino | `backend/scrapers/notino/` | Feed parser plus public/legacy search modules | Separate Notino runtime |
| Orioudh | `backend/scrapers/orioudh/` | `search_stream`, `extract_product_page` | No current adapter mapping |
| Parfumcity | `backend/scrapers/parfumcity/` | `search_stream` | No current adapter mapping |
| Parfumzentrum | `backend/scrapers/parfumzentrum/` | `search_stream`, `extract_product_page` | Yes |
| PerfumeMarket | `backend/scrapers/perfumemarket/` | `search_stream`, `extract_product_page` | No current adapter mapping |
| Sabina | `backend/scrapers/sabina/` | `search_stream`, `extract_product_page` | Yes |

The generic PostgreSQL legacy adapter currently maps Bplatz, Deloox, Sabina, Easycosmetic and Parfumzentrum. Notino has its own feed connector/runtime. Orioudh, Parfumcity and PerfumeMarket are present as scraper code but are not registered in the current PostgreSQL adapter map and do not have active store rows in the inspected DB.

**Live-function status is not certified for all nine packages.** Source presence and passing fixture/contract tests do not prove that a retailer currently permits discovery, product-page fetch, price/stock extraction and publication. Live smoke tests must be run one retailer at a time with bounded queries and read-only/controlled writes.

Evidence observed:
- Latest PR #903 CI: all five checks passed, including parser regression and retailer connector contract. This validates the PR's Deloox restriction and relevant test suites, not all live retailers.
- A previous Fly deployment passed Bplatz refresh and public-search checks.
- Current database has 28 Bplatz, 108 Notino, 6 Parfumzentrum and 21 Sabina active offers.
- Current database has zero Deloox.be and zero Easycosmetic.de active offers.
- Zero offers alone is not enough to label a scraper broken; discovery/fetch/parser/validation results are needed.

## 7. CJ, Notino Feed, XML, CSV and import procedures

### Notino CJ/VIV feed

The CJ/VIV feed is not an unused leftover. It remains part of the PostgreSQL Notino ingestion route:

- `backend/scrapers/notino/affiliate_feed.py`: authenticated feed download, XML parsing, offer normalization, CJ click-link validation.
- `backend/app/connectors/notino_feed.py`: async connector wrapper and cached feed snapshot.
- `backend/app/workers/notino_runtime.py`: Notino discovery/fetch/refresh handlers.
- `backend/app/workers/tasks.py`: registers Notino and legacy worker handlers.
- `backend/app/search/catalog.py`: validates CJ attribution URLs against the stored Notino product destination.
- Scripts include Notino bootstrap, import, GTIN/currency backfills and smoke/diagnostic runners.
- Workflows include Notino CJ import, CJ production monitor, feed diagnosis and catalog diagnostics.

Evidence:
- Feed parser diagnostic run `45293375176` parsed 77,015 offers and validated 77,013 CJ click destinations; two links were rejected for encoded delimiter/control features.
- Feed import workflow `45212851238` completed successfully on 2026-11-23.
- The subsequent production feed monitor failed because it requested `https://scenthunter.fly.dev/catalog-status`, which returned HTTP 404 three times. The current PostgreSQL API exposes `/api/catalog/status`, not `/catalog-status`. Treat this as a stale monitor route until repaired; do not interpret that 404 alone as proof that the feed parser is broken.
- Current Notino store has 108 active offers and recent ingestion runs, although many runs are marked partial.

### XML and CSV

- XML is a live input format for the authorized Notino CJ/VIV feed. Raw XML evidence is retained for audit/reprocessing.
- CSV is an output of the legacy Phase 0 baseline generator, not a current PostgreSQL offer-ingestion format.
- `backend/scenthunter_next_engine/baseline_report.py` reads the canonical JSON catalog plus a local SQLite retailer DB in read-only mode and writes a CSV.
- The workflow `.github/workflows/phase-0-live-baseline.yml` expects secrets `SCENTHUNTER_BASELINE_URL` and `SCENTHUNTER_BASELINE_TOKEN`, then calls durable `/admin/phase0/baseline/*` endpoints.
- The currently deployed `postgres_main.py` mounts only the PostgreSQL catalog router; it does not mount those `/admin/phase0/baseline/*` endpoints. The baseline workflow/worker therefore needs an explicit compatibility decision before it can produce a valid current-state CSV.
- The old baseline scope specifies nine retailer identities, while the current Postgres store registry has six active store rows plus four inactive Deloox market rows. Its scope does not match the current DB registry.

The CSV baseline has **not** been generated or attached as an artifact in this audit. Do not fabricate its counts from the PostgreSQL tables; they have a different data source and grain.

## 8. Phase 0 workflow and migration risks

- The old Phase 0 baseline workflow is read-only with respect to source code but starts or reuses a durable baseline job through the legacy admin API. It is not a harmless static file scan.
- It expects a nine-retailer SQLite/JSON baseline and a route family absent from the current PostgreSQL-only web entrypoint.
- The Notino production monitor still checks the retired `/catalog-status` path.
- Current `main` still contains Deloox country mappings that the draft PR #903 removes. DB inactivity currently blocks those four markets, but code and registry are not yet aligned.
- The worker's queue cutoff excludes every currently queued job. A new queue/backlog reconciliation design is needed before enabling more ingestion.
- The DB has 18 stale-looking `running` ingestion-run rows and a large `partial` history. These need classification before retry or cleanup.
- The current search smoke check failed for `Dior Sauvage` despite health and catalog readiness passing. This is a data/search acceptance issue, not a proof that the web process is down.
- Direct Fly machine/volume/secret inventory and a restore test are still outstanding.

## 9. Phase 0 exit checklist

| Requirement | Result | Evidence / next action |
|---|---|---|
| Freeze unnecessary changes | Partial | `main` protected; open PRs/branches remain. Freeze new feature work during next audit window. |
| Photograph GitHub | Complete for repository metadata/tree | Exact main SHA, branch inventory, open PR inventory, workflow files and key paths captured. |
| Photograph Neon | Complete for operational branch schema and data counts | Operational branch and backup child branch read-queried. Clarify app connection target and stale jobs. |
| Photograph Fly.io | Partial | Deployment/config/health evidence from GitHub Actions; direct machine, volume and secret inventory unavailable in this session. |
| Photograph frontend | Complete at source level | Current frontend calls `/api/catalog/search`; actual UI/browser smoke beyond deployment checks not performed. |
| Map old-system dependencies | Complete at first-pass source level | Monolith, JSON inputs, old workers, adapter and import references listed; full per-symbol call graph still requires automated import/call graph generation. |
| CJ/Notino/XML/CSV/import references | Complete at first-pass source/workflow level | Feed is still operationally relevant; old monitor and baseline workflow have route/data-source mismatch. |
| Inventory all scraper packages | Complete at source level | Nine packages and current adapter registration mapped. |
| Certify all scrapers live | Not complete | Run bounded live discovery/fetch/parse/refresh tests for each supported retailer. |
| Git backup | Complete | Exact `main` SHA preserved on `phase0-git-snapshot-2026-11-24`. |
| Neon backup | Partial | Child branch copy is ready and query-verified; not protected due plan limit; no full restore drill. |
| CSV baseline artifact | Not complete | Existing workflow is incompatible with current app route/store scope; design a PostgreSQL-native read-only baseline before running. |
| Restore procedure | Not complete | Perform a controlled restore test on a disposable branch and document measured recovery. |
| No premature deletion | Complete | No files, branches, tables, rows, volumes or workflows were deleted in this audit. |

## 10. Recommended handoff to Phase 1

Do not start broad cleanup yet. Before Phase 1, resolve these blockers in order:

1. Confirm the exact Neon branch/database endpoint used by the Fly app without exposing connection secrets; record the endpoint/branch identity.
2. Manually run the existing **ScentHunter 2.0 read-only Fly diagnostics** workflow (`.github/workflows/scenthunter-readonly-fly-diagnostics.yml`). Record app/machine/volume state, runtime DB backend and mounted-file presence; record secret *names* only, never values.
3. Replace or adapt the legacy SQLite Phase 0 baseline workflow with a read-only PostgreSQL baseline that matches the approved active retailer scope. Do not enqueue a legacy baseline job on the current app.
4. Reconcile the 73,763 pre-cutoff queued jobs and 18 running ingestion runs with a dry-run plan before any state change.
5. Align the Postgres store registry with the approved retailer list and Deloox.be-only policy. Decide explicitly whether Orioudh, Parfumcity and PerfumeMarket are in or out of the first supported release.
6. Run controlled live smoke tests for each supported scraper and retain evidence for discovery, product fetch, price, currency, stock, URL/domain and persistence.
7. Run a disposable-branch restore drill for the Neon backup and preserve restore steps/results.
8. Only after these gates pass, approve a per-file dependency map and begin narrow Phase 1 refactoring.

**Safety decision:** No legacy module, scraper, feed parser, JSON catalog, workflow, database row or historical record is approved for deletion by this Phase 0 report.
