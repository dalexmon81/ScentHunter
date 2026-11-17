# Phase 10 recovery inventory — 2026-11-17

Status: **preserved snapshot; not merged into main.**

## Preserved source
- Source branch: `phase10/ops-phase11-integrated`
- Exact source commit: `afba68f6f3cf98bab98c5463437d85bd279d0700`
- Frozen pointer: `recovery/phase10-preserved-2026-11-17`
- Current main at audit: `600e5f939f0657c3ee4cb0f4854828edd9b064e6`

## Divergence
GitHub compare reports the Phase 10 branch as **739 commits ahead and 73 behind main**. The branches are substantially divergent. A direct merge is not an acceptable recovery strategy.

Tree comparison (recursive Git trees, not truncated):
- Main: 290 tracked paths
- Phase 10: 431 tracked paths
- Phase 10-only files: 158
- Main-only files: 19

## Important Phase 10-only components to preserve and evaluate
- Universal store connectors under `backend/app/connectors/`
- Celery ingestion pipeline under `backend/app/workers/`
- Canonical identity, review queue, normalization and offer services under `backend/app/services/`
- PostgreSQL/Alembic migrations 0003–0015
- Search, readiness, rollout, offer matching and promotion modules
- Connector fixtures and extensive backend tests
- Staging worker and catalog-first CI workflows

## Important main-only components to preserve
- `backend/app/search/catalog.py`
- `backend/scripts/persist_bplatz_liquid_brun.py`
- `backend/scripts/persist_bplatz_phase2_live_offer.py`
- `backend/scripts/check_bplatz_liquid_brun_live.py`
- `backend/tests/test_catalog_first_search.py`
- `backend/tests/test_bplatz_live_offer_check.py`
- `tests/fixtures/bplatz/liquid-brun-100ml-user-observation.json`
- Current-main workflow files for the Bplatz observation and Liquid Brun pilot
- Current-main documentation for the catalog-first pilot

## Key semantic overlap to review
- Both trees contain `backend/app/db.py`, but Phase 10 has an explicit `SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL` deployment guard that is not in the current-main version.
- Phase 10 has a database-backed search implementation in `backend/app/search/catalog.py`; main has a separate HTTP adapter and search service structure. These must be reconciled at the API/service boundary, not copied over blindly.
- The Phase 10 ingestion task stages raw evidence and keeps matching/promotion as separate gates. This behavior is a critical invariant to preserve.
- Main contains the recently merged PR #772 Bplatz/Liquid Brun pilot and related tests/workflows. Phase 10 does not contain those exact main-only pilot files.

## CI limitation
No workflow runs were returned for the exact Phase 10 tip SHA `afba68f...`. Earlier individual PR workflow successes are not evidence that this current branch tip passes as a whole. Do not call Phase 10 fully validated until CI is run against the exact frozen SHA or a reconciled candidate.

## Recovery decision
Keep the Phase 10 snapshot intact. Port selected modules only after file-by-file semantic comparison and tests against the current-main pilot. No merges, deployments, database migrations or live retailer actions were performed.
