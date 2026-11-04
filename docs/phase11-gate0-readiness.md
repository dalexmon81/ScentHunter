# Gate 0 — readiness audit (2026-11-04)

## Decision

**STATUS: BLOCKED — do not start shadow traffic or the 5% canary.**

This audit is based on repository files and pull-request records. It does not claim to have queried a live retailer, staging database, Fly.io, Neon, or Upstash.

## Evidence checked

### Phase 5 pipeline — PR #343

PR #343 is open and draft. Its current implementation includes:
- PostgreSQL 16 and Redis 7.4 disposable GitHub Actions services;
- Alembic migrations applied twice in the runtime integration job;
- canonical catalog seed;
- a real Celery worker registered against Redis;
- a scheduler task querying the seeded PostgreSQL offers table;
- a durable dead-letter write/readback.

The runtime test explicitly asserts zero refresh jobs and zero configured stores, and deliberately performs no retailer HTTP calls. The seed report explicitly sets `offers_imported: 0`. Therefore this is a valid infrastructure integration test, but not a live-offer end-to-end proof.

### Phase 5 staging worker — PR #344

PR #344 is open and draft. It defines a separate Fly app/configuration with no production volume or public HTTP service. Its runbook requires separate staging Neon PostgreSQL and Upstash Redis credentials before deployment. No such credentials or staging deployment were verified in this audit. The existing zero-cost staging plan also says not to deploy a persistent Fly worker without checking and approving its compute cost.

### Existing Bplatz Phase 2 evidence

PR #313 is merged and records a successful proof of Bplatz persistence through the normal legacy hydration worker, including offer upsert, price history, match audit, duplicate checks and database integrity verification.

That proof is useful but does **not** satisfy the Phase 5 PostgreSQL/Celery vertical slice:
- it is the existing Bplatz Phase 2 persistence path, not the new PostgreSQL + Redis/Celery runtime;
- the committed Bplatz fixture is Liquid Brun, not Dior Sauvage EDP 100 ml;
- the Phase 5 seed still imports zero retailer offers and seeds only the Bplatz store row.

Do not treat the merged Bplatz proof as evidence that Dior Sauvage has a published Phase 5 offer.

### Connector choice

The Phase 5 registry contains nine connectors. Notino uses the authorized CJ/VIV XML affiliate feed; the adapter parses feed data without writing to the database. However, no feed fixture or live staging feed response was found during this audit, and no feed credentials or runtime secret were inspected.

Bplatz has a captured product-page fixture and a proven legacy persistence path, but the fixture is for a different fragrance. A connector must not be declared suitable for Dior merely because it is already integrated.

## Gate 0 checklist

| Requirement | Status | Evidence / next action |
|---|---|---|
| Isolated PostgreSQL + Redis runtime in CI | PASS | Disposable CI services and real Celery worker test are defined in PR #343 |
| Alembic repeatability in disposable CI | PASS | Workflow runs `alembic upgrade head` twice |
| Canonical catalog seed | PASS | Seed script validates and imports identities/declared variants |
| Real Phase 5 offers in PostgreSQL | BLOCKED | Seed reports `offers_imported: 0`; no live ingestion evidence |
| Dior Sauvage EDP 100 ml catalog variant | PARTIAL | Explicit 100 ml variant and matcher-aligned canonical key added on Phase 5 branch from Dior's official product page; CI seed and staging UUID readback still pending |
| Authorized pilot source for Dior | NOT VERIFIED | Confirm a specific connector has an authorized, stable source record for this SKU |
| Real ingestion → staging → matching → promotion | NOT VERIFIED | CI intentionally avoids retailer HTTP calls |
| Offer readback from PostgreSQL | NOT VERIFIED | Must assert one published offer linked to the exact variant UUID |
| Refresh via Celery and price/stock readback | PARTIAL | Worker infrastructure is tested, but there is no real offer to refresh |
| Staging Neon/Upstash isolated resources | NOT VERIFIED | Must be confirmed by owner in provider consoles |
| Fly staging worker deployed | NOT RUN | Requires staging secrets and explicit cost approval |
| Production untouched | PASS (this audit) | No production endpoint, database, secret, worker or deployment was accessed |

## Exact acceptance test still required

For Dior Sauvage EDP 100 ml and one explicitly approved store:
1. Resolve the exact canonical fragrance and variant UUID from the migrated PostgreSQL seed.
2. Run one controlled discovery/fetch using the selected connector and approved source.
3. Persist original source evidence and an ingestion run.
4. Normalize and match the raw offer to the exact variant; ambiguous matches must remain unpublished.
5. Promote only if URL, positive price, ISO currency, explicit availability, timestamp and store status pass validation.
6. Read back the published offer in a new database session and verify exact variant linkage.
7. Enqueue one refresh through Redis/Celery, consume it with a real worker, and verify price/availability observation and history.
8. Confirm an ordinary product search reads PostgreSQL/indexed data and does not call the retailer.
9. Attach sanitized run IDs, offer UUID, variant UUID, timestamps, test output and CI links to the PR.

## Safe next action

Do not invent a retailer offer, seed a synthetic published offer, scrape an unapproved source, or reuse the Bplatz Liquid Brun proof as a Dior result.

The next implementation step is a **staging-only, manually gated Notino pilot run** once the owner confirms:
- that the CJ/VIV Notino.fr feed entitlement is active and its feed access is configured in staging;
- that dedicated staging PostgreSQL and Redis endpoints exist;
- whether a persistent Fly worker's cost is approved, or the test must run only in disposable CI.

Until these conditions are met, Gate 0 remains blocked and the new API must serve 0% user traffic.
