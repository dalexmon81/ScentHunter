# Gate 0 — readiness audit (2026-11-05)

## Decision

**STATUS: BLOCKED — do not start shadow traffic or the 5% canary.**

The selected pilot remains **Bplatz — French Avenue Liquid Brun Eau de Parfum 100 ml**. Notino/Dior references in older planning material are superseded and are not the active pilot.

This audit distinguishes CI fixtures, staging infrastructure, retailer authorization, and live offer evidence. Passing one category does not imply another.

## Current verified evidence

### Phase 5 staging infrastructure

The isolated Fly.io staging deployment [run 42085586218](https://github.com/dalexmon81/ScentHunter/actions/runs/42085586218) completed successfully. All 20 job steps passed, including isolated ingestion/connector tests, Fly token scope verification and staging secret application, worker deploy with one app worker and zero Beat machines, worker startup and broker connection, read-only database/store safety audit, Alembic migrations, canonical brand-alias normalization, canonical catalog seed without activating a retailer, non-root worker verification, Celery broker ping, and queued-task smoke execution.

The seeded staging catalog contains **60 brands, 1,389 fragrances, and 512 variants**. It reports **stores=0, offers=0, invalid_active_offers=0**. The deployment includes the bounded manual-only Bplatz task from merged PR #360.

This proves staging deployment and smoke execution. It does not prove retailer authorization, a live offer, offer refresh, price history, or end-to-end catalog-first search.

### Bplatz bounded pilot implementation

PR [#360](https://github.com/dalexmon81/ScentHunter/pull/360) added a manual-only task for the exact Bplatz Liquid Brun EDP 100 ml product page. It is restricted to the approved product path, records source evidence against an ingestion run, and passes data through the existing validation/matching/promotion pipeline. It requires an explicit authorization reference.

The offline fixture tests passed in workflow [42073836383](https://github.com/dalexmon81/ScentHunter/actions/runs/42073836383), with 39 tests passing. The task is deployed to staging but **has not been invoked**. The authorization-reference field is a safeguard, not proof that permission exists.

### Bplatz permission request

Bplatz's official [Terms and Conditions](https://en.bplatz.de/pages/purchase-clauses) and [Privacy Policy](https://en.bplatz.de/pages/Data-protection) were reviewed. They do not expressly authorize automated collection or scraping. robots.txt could not be retrieved, so no allow/disallow conclusion is recorded.

A permission request was sent to **orders@bplatz.de** on 2026-11-05. It asks for an approved API/feed/affiliate feed or written permission for a limited one-product test, restricted to product URL, price/currency, and availability. **No reply or authorization has been received yet.** No live Bplatz request has been made.

Do not invoke the task until a permitted access method is confirmed and the authorization reference records the actual approval.

### Offline quality evidence

- PR #347 adds the Bplatz offline fixture validation matrix.
- PR #343 workflow [41967935150](https://github.com/dalexmon81/ScentHunter/actions/runs/41967935150) passed Bplatz fixture parsing, Celery discovery, raw artifact SHA-256, and artifact-to-ingestion-run linkage.
- PR #343 workflow [41968439231](https://github.com/dalexmon81/ScentHunter/actions/runs/41968439231) passed timeout retry/quarantine isolation, wrong-size rejection (50 ml versus canonical 100 ml), and ambiguous duplicate-GTIN review without automatic matching.
- Latest PR #345 CI checks passed: backend parser [42074248195](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248195), Next Engine Shadow Integration [42074248249](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248249), and Hydration Regression [42074248330](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248330).

These are offline fixture/stub or CI checks. They are not evidence of a current retailer offer or live authorized ingestion.

## Gate 0 checklist

| Requirement | Status |
|---|---|
| Disposable PostgreSQL/Redis/Celery CI integration | PASS — synthetic CI only |
| Bplatz Liquid Brun historical fixture and validation matrix | PASS — historical/offline only |
| Bplatz artifact linkage and negative-path tests | PASS — fixture/stub CI only |
| Bounded manual Bplatz task implemented | PASS — merged and deployed to staging; not invoked |
| Isolated staging deploy, migrations, canonical seed | PASS — run 42085586218 |
| Staging worker non-root, Celery ping and queued smoke task | PASS — run 42085586218 |
| Bplatz automated access permission/method | BLOCKED — email sent; awaiting reply |
| Retailer activated in staging | NOT RUN — stores=0 |
| Real offer persisted through Phase 5 PostgreSQL | NOT RUN — offers=0 |
| Real Celery price/stock refresh and price history | NOT RUN |
| Catalog search proven to avoid synchronous retailer requests | NOT RUN |
| Rollback/readiness proof for live traffic | NOT COMPLETE |
| Shadow/canary traffic | BLOCKED — 0% |

## Required next steps

1. Await Bplatz's response. If it confirms an approved API/feed or grants written permission, record the exact scope and approval reference before any live request.
2. In parallel, evaluate alternative retailers that provide a documented API, product feed, or affiliate feed with terms permitting the intended use. Do not assume that an affiliate account alone authorizes scraping or feed reuse.
3. For the first retailer with a confirmed permitted method, configure it explicitly in isolated staging and run a narrowly bounded pilot. Keep the Bplatz task dormant unless Bplatz approval arrives.
4. Verify one genuine offer is persisted, validated, refreshed by Celery, represented in price history, and returned by catalog-first search without a synchronous retailer request.
5. Complete rollback, monitoring, and readiness checks before considering shadow traffic. Start with shadow only after Gate 0 approval; consider 5% canary only after shadow evidence is acceptable.

Do not create a synthetic published offer, scrape around a block, activate a retailer without a permitted access method, or enable shadow/canary traffic while the gate is blocked.

**Gate 0 remains BLOCKED; shadow/canary remain 0%.**