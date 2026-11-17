# Phase 10 selective recovery audit — 2026-11-17

Status: **working branch created from current main; no Phase 10 code has been merged or copied yet.**

## Branches and exact snapshots

- Current main at audit start: `defe49283754281c81f540fbdc3ef5588097c692`.
- Preserved Phase 10 source: `recovery/phase10-preserved-2026-11-17`.
- Original Phase 10 source branch: `phase10/ops-phase11-integrated`, source commit `afba68f6f3cf98bab98c5463437d85bd279d0700`.
- New selective-port work branch: `recovery/phase10-selective-port-2026-11-17`, created from `main`.
- Phase 10 vs main comparison: 201 changed paths (161 added, 40 modified); current compare reports 739 commits ahead and 74 behind. The old inventory's "73 behind" count is stale.

## Recovery decision

Do not merge the Phase 10 branch wholesale. Preserve it as an immutable reference and port only coherent, independently testable slices to the selective-port branch.

### Candidate components

1. **Connector contract and adapters** — `backend/app/connectors/base.py`, runtime registry, then individual retailer connectors. The contract returns captured evidence and does not write directly to canonical catalog tables.
2. **Ingestion orchestration** — Celery queue topology and ingestion tasks. Preserve the stage → normalize → validate → match → promote separation, raw evidence retention, retry/dead-letter handling, and store-scoped quarantine.
3. **Matching and promotion** — offer matcher, matching worker and promotion gate. Publication must require an explicit canonical variant match and validated price/currency/URL/availability/freshness.
4. **Normalization and offer identity** — normalization, identity and ranking services, reviewed against current-main contracts before porting.
5. **Database evolution** — migrations 0003–0015 only after validating the complete Alembic graph, model parity, downgrade behavior and PostgreSQL/SQLite compatibility.

## Files that must not be copied blindly

- `backend/app/db.py` is modified in Phase 10. Current main already has the opt-in PostgreSQL guard from merged PR #774. Retain current main's database URL policy; do not reintroduce a generic `DATABASE_URL` fallback or change SQLite defaults.
- `backend/app/models/catalog.py` is modified in Phase 10 (+203/-3 in the compare). It carries schema changes used by later migrations and services. Port schema and model changes as one reviewed unit, not as an isolated file.
- `backend/app/models/__init__.py` is modified; model exports must remain compatible with current imports.
- `backend/app/services/ingestion_persistence.py` is modified (+41/-14). Its current-main version must be compared before any replacement.
- Current main's `backend/app/search/catalog.py` and the merged PR #772 Bplatz/Liquid Brun pilot are protected integration points. Phase 10 search code must be reconciled with them, not substituted wholesale.

## Exact-head CI findings for recovery PR #776

Head: `dae3812826db9c42ae29ec6aeee3f93dccb260dc`.

- Recovery catalog validation: **success**.
- Hydration regression: **success**.
- Next Engine shadow integration: **success**.
- Bplatz Phase 2 worker wiring isolated tests: **success**.
- Backend parser regression workflow: **failure**, but the failure is not currently evidence of a parser defect. The failed remote job streamed the live Notino feed: it downloaded 34,465,208 bytes and successfully parsed/staged 45,000 records with zero rejects before the 1,830-second SSH command timeout terminated it (exit 124). A separate live-feed runner job completed successfully. The remote job label says "CJ feed" while its log reports `NOTINO_PROFILE`; this naming mismatch needs correction.
- Do not rerun the full remote feed job unchanged. Replace it with a bounded, read-only sample or a controlled timeout/batch strategy, and make the job label accurately describe the feed.

## Immediate implementation order

1. Compare the Phase 10 connector contract and one connector against current-main interfaces; port the smallest contract slice with focused tests.
2. Port Celery topology and a single no-publication ingestion task; test that it only stages raw evidence.
3. Port matching and promotion as separate, gated stages.
4. Reconcile model/schema changes and migrations as a separate PR after service-level tests pass.
5. Run exact-head CI for each slice. No production deployment, production database migration, or live retailer writes during this recovery.

## Safety invariants

- No live retailer search in the user search request path.
- Connectors never write canonical products or publish offers directly.
- Unmatched or ambiguous evidence is never promoted.
- A retailer failure must not block other stores.
- No guessed concentration, size, GTIN, price, stock or shipping values.
- Main's Bplatz pilot and its opt-in behavior remain intact.
