# Gate 0 — readiness audit (2026-11-05)

## Decision

**STATUS: BLOCKED — do not start shadow traffic or the 5% canary.**

The selected pilot for Phase 11 is **Bplatz — French Avenue Liquid Brun Eau de Parfum 100 ml**. Notino/Dior references in older planning material are superseded and are not the active pilot.

This audit uses repository and GitHub Actions evidence. The manual staging deployment/smoke test is now verified by run [42042272812](https://github.com/dalexmon81/ScentHunter/actions/runs/42042272812). It does not claim a live Bplatz request or a real retailer offer.

## Evidence

### Phase 5 infrastructure — PR #343

The CI integration path exercises PostgreSQL 16, Redis 7.4, Alembic migrations, canonical seed, Celery worker registration and dead-letter readback. It remains a synthetic/disposable CI environment. The seed reports zero imported retailer offers; no live retailer request is part of this proof.

### Bplatz pilot identity

The historical fixture identifies:
- Product: French Avenue Liquid Brun EDP 100 ml
- Captured Shopify variant: `54015243419916`
- Captured SKU/GTIN: `6290360375694`
- Legacy product: `SH-0030`
- Legacy variant: `VAR-f87146c82d167f4c`
- Fixture SHA-256: `9f76b00bc7472ccd389116302f06e2e02f258dc17fee7f43371993f79284c017`

These are fixture identifiers, not current stock, price, authorization, or Phase 5 database UUIDs.

### Bplatz Gate B1

PR #347 adds an offline fixture validation matrix. Its push and pull-request Actions runs passed. Coverage includes stock states, invalid prices, currency handling, size/concentration parsing, and absent SKU/GTIN handling.

A Bplatz-specific artifact-linkage test was added in PR #343 commit `99c2842287df681d8cd5c5abece4aeef97c9068f`. Workflow run [`41967935150`](https://github.com/dalexmon81/ScentHunter/actions/runs/41967935150) completed successfully: both `ingestion-pipeline` and `runtime-integration` jobs passed. It runs the historical Liquid Brun HTML fixture through the Bplatz parser/connector and Celery discovery task, verifying unchanged bytes and SHA-256, artifact-to-ingestion-run linkage, and the raw-evidence artifact reference.

Further Bplatz-specific negative-path tests passed in PR #343 workflow run [`41968439231`](https://github.com/dalexmon81/ScentHunter/actions/runs/41968439231), commit `b609eaa353355fe03a6540035fb028ef87f86a83`. Both `ingestion-pipeline` and `runtime-integration` jobs passed. Coverage verifies timeout retry and quarantine isolation (other stores remain active), rejection of a 50 ml record against the 100 ml canonical variant, and ambiguous duplicate-GTIN review with no automatic match.

These are fixture/stub-based tests in offline, disposable CI only. They are not live ingestion, a current retailer offer, or persistent staging proof.

### Live staging worker evidence — 2026-11-05 (successful follow-up)

Workflow run [42042272812](https://github.com/dalexmon81/ScentHunter/actions/runs/42042272812) reached the actual Fly.io staging environment and completed successfully. Its logs confirm:

- The isolated worker image was deployed and the process groups were scaled to one `app` worker and zero `beat` machines.
- PostgreSQL identity matched the guarded staging fingerprint for database `neondb`, schema `public`, via `SCENTHUNTER_CATALOG_DATABASE_URL`.
- Alembic migration completed and the database reported revision `0007_ingestion_dead_letters`, with all required catalog/ingestion tables present.
- The pre-seed audit reported zero store rows.
- The Celery worker loaded the ingestion tasks/queues, connected to Redis over TLS, and logged `ready`. Beat remained intentionally disabled.

**The first staging attempt** (run [41911919350](https://github.com/dalexmon81/ScentHunter/actions/runs/41911919350)) failed at the duplicate `viktor-rolf` slug. The correction was merged in PR [#359](https://github.com/dalexmon81/ScentHunter/pull/359); duplicate PR #348 was closed.

**Successful follow-up — run [42042272812](https://github.com/dalexmon81/ScentHunter/actions/runs/42042272812):** the canonical seed completed with 60 brands, 1,389 fragrances and 512 variants; `stores=0`, `offers=0`, and `invalid_active_offers=0`. The run verified all required tables and Alembic revision `0007_ingestion_dead_letters`, Celery `pong`, and a queued smoke task returning `{'ok': True}`. It also verified one non-root app worker and zero Beat machines.

This is persistent staging infrastructure and catalog-seed evidence, **not** a Bplatz offer ingestion. The seed intentionally did not activate a retailer. The run reported all three Notino CJ feed credentials absent; Notino remains deferred.

### Source access and infrastructure

- Current Bplatz terms and the permitted automated access method: **NOT VERIFIED**.
- Persistent isolated PostgreSQL staging identity: **VERIFIED for the guarded Neon fingerprint in PR #344 run 41911919350**; sustained availability/backup-restore still NOT VERIFIED.
- Redis TLS connectivity from the staging worker: **VERIFIED by startup logs**; dedicated Redis isolation/retention configuration still NOT VERIFIED.
- Real Bplatz offer persisted through Phase 5: **NOT RUN** (staging still has zero offers and zero stores).
- Celery refresh of a real Bplatz offer: **NOT RUN** (only the generic queued smoke task has been verified).
- Catalog search proven to avoid synchronous retailer requests: **NOT RUN**.
- Fly staging worker deployment: **VERIFIED** by run 42042272812; production deployment: **NOT RUN**.

## Gate 0 checklist

| Requirement | Status |
|---|---|
| Disposable PostgreSQL/Redis/Celery CI integration | PASS — synthetic CI only |
| Bplatz Liquid Brun historical fixture | PASS — historical evidence only |
| Offline Bplatz B1 validation matrix | PASS — PR #347 |
| Bplatz fixture artifact/run linkage | PASS — PR #343 run 41967935150, offline only |
| Retry/quarantine and wrong-size/ambiguous-match coverage | PASS — PR #343 run 41968439231, offline fixture/stub tests only |
| Bplatz automated access permission/method | NOT VERIFIED |
| PostgreSQL staging identity and schema/migrations | PASS — PR #344 run 41911919350; uptime/restore still unverified |
| Redis TLS broker connectivity | PASS — worker startup log; dedicated-instance isolation not independently verified |
| Canonical staging seed | BLOCKED — duplicate brand slug `viktor-rolf`; draft fix PR #348 |
| Celery queued task execution | NOT VERIFIED — workflow failed before ping/smoke steps |
| Real offer in Phase 5 PostgreSQL | NOT RUN |
| Real Celery refresh and price history | NOT RUN |
| Search with zero synchronous Bplatz requests | NOT RUN |
| Shadow/canary traffic | BLOCKED — 0% |

## Required next steps

1. Review Bplatz's current terms and confirm the exact permitted access method before any live request. If permission is unclear, stop.
2. Resolve the duplicate-brand seed defect in draft PR #348; run unit/regression CI without triggering a staging deployment.
3. Perform a read-only staging count/identity audit after the failed seed, accounting for the separately committed one-row brand-alias normalization.
4. Only after review, explicitly approve a controlled seed retry; then verify expected canonical counts and zero stores/offers.
5. Verify the worker remains up, answers Celery ping, and executes the side-effect-free queued smoke task. Keep Beat disabled.
6. Separately verify Bplatz source-access permission before any retailer request. Only then consider a bounded Liquid Brun EDP 100 ml pilot.

Do not create a synthetic published offer, substitute another product, scrape around a block, deploy a persistent worker without cost approval, or enable shadow/canary traffic.

**Gate 0 remains BLOCKED and new-API user traffic remains 0%.**
