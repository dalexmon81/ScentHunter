# ScentHunter Next Engine — foundation (not wired into production)

This package is an isolated first implementation of the canonical data path.
It does not change the legacy engine, its SQLite database, `product_catalog.json`,
or frontend behavior.

## Scope of this first slice
- Read the existing canonical catalog without rewriting it.
- Keep retailer offers separate from canonical product/variant identity.
- Resolve variants only when the catalog provides an explicit matching variant.
- Aggregate offers by canonical product + canonical variant, never by size alone.
- Expose opt-in diagnostic endpoints only when the existing `SCENTHUNTER_NEXT_ENABLED`
  flag is enabled.

## Important limits
- Retailer scraper adapters and production search orchestration are intentionally not
  connected yet. The diagnostic endpoint accepts a supplied offer; it does not pretend
  to be a live retailer scrape.
- This foundation must pass tests and be reviewed before any production rollout.
- `runtime.py` uses the existing `ProductMatcher` as a candidate matcher, then independently
  resolves the canonical variant ID from `product_catalog.json`. It does not trust the
  matcher's generated `variant_id` as a canonical variant identifier.
- The catalog schema is read defensively. If a product or variant cannot be resolved
  unambiguously, the offer remains unresolved.

## Files
- `models.py`: immutable domain contracts.
- `catalog_repository.py`: read-only catalog access.
- `matching.py`: matching + explicit canonical variant resolution.
- `aggregation.py`: strict aggregation.
- `service.py`: pipeline orchestration for already-collected offers.
- `runtime.py`: optional FastAPI diagnostic router.
- `tests/test_next_engine.py`: contract tests with synthetic fixtures.

## Rollout gate
Do not enable this in production until:
1. tests pass in the repository's actual environment;
2. the real catalog schema is confirmed against a full catalog read;
3. retailer adapters are added and tested per store;
4. a shadow comparison is performed against legacy search;
5. database isolation and rollback are verified.
