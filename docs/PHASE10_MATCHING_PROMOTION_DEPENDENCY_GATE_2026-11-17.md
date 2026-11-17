# Phase 10 matching and promotion dependency gate — 2026-11-17

## Decision

Do not port `offer_matcher.py` or `offer_promotion.py` onto current `main` yet. Their imports and runtime assumptions are not satisfied by the current-main schema. Porting either file alone would create a misleading, non-runnable implementation.

This is a dependency audit only. No schema, migration, worker, production database, retailer connector, or deployment was changed.

## Verified gaps on current main

Compared with `recovery/phase10-preserved-2026-11-17`:

1. `backend/app/models/catalog.py` on main has no `ProductVariant.is_mini`. The preserved matcher reads this field when reconstructing legacy packaging identity.
2. Main `Store` has no `offer_ttl_minutes`. The preserved `promote_offer()` requires an explicit positive store TTL and rejects publication when it is not configured.
3. Main `backend/app/models/__init__.py` does not export `CanonicalIdentityReview`; the preserved matcher imports it through `canonical_identity_review_queue.py`.
4. Main models do not include `CanonicalIdentityReview`, `StoreAuthorization`, `IngestionArtifact`, or `IngestionDeadLetter` exports. The preserved source adds these models and related persistence support.
5. The preserved `ProductVariant.size_ml` uses `Numeric(10, 4)`; main uses an integer. This matters because the normalization/matching layer accepts fractional ml values and must not silently truncate them.
6. The preserved promotion gate imports the supported-currency policy and requires explicit availability (`in_stock` or `out_of_stock`), HTTPS URL, positive finite Decimal price, active store, timezone-aware capture time, and a non-expired observation.

## Migration graph found in the preserved branch

Current main has only:
- `0001_initial_catalog_schema.py`
- `0002_ingestion_raw.py`
- `0003_store_domain.py`

The preserved branch adds a second child of `0002` named `0003_variant_mini_packaging`, then a merge revision `0004_merge_store_domain_and_variant_mini` with parents `0003_store_domain` and `0003_variant_mini_packaging`.

The subsequent chain inspected:
- `0005_canonical_identity_reviews`
- `0006_ingestion_artifacts`
- `0007_ingestion_dead_letters`
- `0008_variant_size_precision`
- `0009_live_ingestion_uniqueness`
- `0010_store_offer_ttl`
- `0011_catalog_search_fts`
- `0012_store_authorizations`
- `0013_store_shipping_rates`

Do not copy these migrations as a batch without validating the full Alembic graph, upgrade and downgrade behavior, SQLite table-copy behavior, PostgreSQL DDL, and the 0004 migration's PostgreSQL `alembic_version.version_num` widening.

## Safe next implementation order

1. Reconcile the migration graph with current main, starting with the 0003 branch split and 0004 merge revision.
2. Build migration tests from a clean database and from a database already at current main's 0003 revision. Verify both SQLite and disposable PostgreSQL.
3. Port only the model fields/tables required by conservative matching and promotion, preserving current-main database URL policy and SQLite default.
4. Add contract tests for legacy variant matching, review queue idempotency, offer TTL expiry, stale/future timestamps, currency policy, explicit availability, and retailer identity idempotency.
5. Only then port the conservative matcher and promotion gate.
6. Only after those gates pass, wire ingestion workers. Keep all retailer collection disabled until explicit store authorization is represented and checked.

## Invariants

- Never auto-match on fuzzy name similarity.
- A verified GTIN must agree with full normalized variant identity.
- Uncertain identity remains unmatched and enters durable review.
- A matched offer is not automatically published; publication revalidates evidence and freshness.
- No retailer is enabled without a recorded authorization state and permitted collection method.
- No changes to `main`, production DB, secrets, or deployment from this recovery branch.
