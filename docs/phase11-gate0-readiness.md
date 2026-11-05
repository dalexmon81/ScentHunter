# Gate 0 — readiness audit (2026-11-05)

## Decision

**STATUS: BLOCKED — do not start shadow traffic or the 5% canary.**

The selected pilot for Phase 11 is **Bplatz — French Avenue Liquid Brun Eau de Parfum 100 ml**. Notino/Dior references in older planning material are superseded and are not the active pilot.

This audit is based on repository and GitHub Actions evidence only. It does not claim a live Bplatz request, persistent staging access, or a real retailer offer.

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

A Bplatz-specific test was added in PR #343 commit `99c2842287df681d8cd5c5abece4aeef97c9068f`. Workflow run [`41967935150`](https://github.com/dalexmon81/ScentHunter/actions/runs/41967935150) completed successfully: both `ingestion-pipeline` and `runtime-integration` jobs passed. The test runs the committed historical Liquid Brun HTML fixture through the Bplatz parser/connector and Celery discovery task, then verifies the unchanged HTML bytes and SHA-256, artifact-to-ingestion-run linkage, and raw-evidence artifact reference.

This proves the Bplatz fixture artifact path in offline, disposable CI only. It is not a live ingestion, current retailer offer, or persistent staging proof.

### Source access and infrastructure

- Current Bplatz terms and the permitted automated access method: **NOT VERIFIED**.
- Persistent isolated PostgreSQL/Redis staging: **NOT VERIFIED**.
- Real Bplatz offer persisted through Phase 5: **NOT RUN**.
- Celery refresh of a real Bplatz offer: **NOT RUN**.
- Catalog search proven to avoid synchronous retailer requests: **NOT RUN**.
- Fly worker deployment/cost approval: **NOT RUN**.

## Gate 0 checklist

| Requirement | Status |
|---|---|
| Disposable PostgreSQL/Redis/Celery CI integration | PASS — synthetic CI only |
| Bplatz Liquid Brun historical fixture | PASS — historical evidence only |
| Offline Bplatz B1 validation matrix | PASS — PR #347 |
| Bplatz fixture artifact/run linkage | PASS — PR #343 run 41967935150, offline only |
| Retry/quarantine and wrong-size/ambiguous-match coverage | OPEN |
| Bplatz automated access permission/method | NOT VERIFIED |
| Isolated persistent staging resources | NOT VERIFIED |
| Real offer in Phase 5 PostgreSQL | NOT RUN |
| Real Celery refresh and price history | NOT RUN |
| Search with zero synchronous Bplatz requests | NOT RUN |
| Shadow/canary traffic | BLOCKED — 0% |

## Required next steps

1. Complete Bplatz-specific retry/quarantine isolation and wrong-size/ambiguous-match rejection tests, reusing generic Phase 5 tests where they already cover the behavior.
2. Review Bplatz's current terms and confirm the exact permitted access method before any live request. If permission is unclear, stop.
3. Verify isolated staging PostgreSQL and Redis without exposing secrets or using production resources.
4. Only after explicit source-access approval and staging verification, run one bounded pilot for the exact Liquid Brun EDP 100 ml variant.
5. Verify persistence, one Celery refresh, price history, and catalog search with no synchronous retailer request.

Do not create a synthetic published offer, substitute another product, scrape around a block, deploy a persistent worker without cost approval, or enable shadow/canary traffic.

**Gate 0 remains BLOCKED and new-API user traffic remains 0%.**
