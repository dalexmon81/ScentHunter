# Integration and rollout

## Phase 0 — isolated package (implemented)

The new package lives separately from the legacy catalog. It has its own domain model, retailer adapter registry, deterministic identity resolver, transactional SQLite repository, durable discovery/hydration task queue, leased worker, ingestion service, read-only search service, opt-in API, shadow comparison and bounded telemetry. The Deloox page adapter is tested with static fixtures; it is not yet used for production discovery.

## Phase 1 — offline shadow comparison (implemented)

1. Copy `scenthunter_next_engine/` under `backend/` as `backend/scenthunter_next_engine/`.
2. Add this import and call in `backend/main.py`, after `app = FastAPI(...)` and before requests are served:

   ```python
   from scenthunter_next_engine.runtime import mount_next_engine
   mount_next_engine(app)
   ```

3. Keep `SCENTHUNTER_NEXT_ENABLED` unset or `0` initially. This must leave all current routes untouched.
4. Configure a distinct `SCENTHUNTER_NEXT_DB` path and set `SCENTHUNTER_LEGACY_DB` to the actual legacy DB path before enabling the flag. The app refuses to use the same resolved path.
5. Enable `/v2` only in a staging deployment first. Confirm `/v2/health`, `/v2/metrics` and empty `/v2/search` responses; no retailer is ingested by merely mounting the API.
6. The offline JSON snapshot runner is available as `python -m scenthunter_next_engine.shadow_runner --legacy legacy.json --next next.json --output report.json`. It compares coverage, URLs, prices/currencies, and variant-size identity without database/network side effects. A read-only exporter for the legacy database and a read-only exporter for the next-engine database are available. Export both snapshots, then run the comparison; neither exporter writes to its source database.

## Phase 2 — retailer adapter canary

The Deloox adapter handles fixture product pages, extracts a Product JSON-LD object, validates price/currency and maps explicit product attributes. It classifies 403 as access denied and 429 as rate limited; it does not retry or bypass these responses. Its discovery callback is injectable but not wired to the legacy discovery implementation yet. Build and validate discovery as a separate unit before running it.

Before any retailer ingestion, require fixture parity and a small bounded staging canary. Keep the legacy search route as rollback path.

## Phase 3 — acceptance gates

- All offline tests pass.
- Replaying identical observations is idempotent.
- A parser/network failure cannot erase a valid offer.
- Older observations cannot roll back a newer price.
- GTIN/MPN are treated as trade-item identifiers; variants remain distinct by size/concentration/pack and identifiers.
- No price comparison crosses currencies without conversion.
- Search has no scraper/network side effects.
- No production database mutation until shadow parity is reviewed.

## Current status and limits

- Offline suite: see `TEST_RESULTS.txt` for the latest locally executed count.
- Implemented: models, exact identity rules, Deloox product-page adapter, adapter registry, ingestion, separate SQLite persistence, durable leased queue with classified retries and audited DEAD replay, worker orchestration, read-only search, opt-in API, feature-flag/database-path guards, counters/latency summaries, legacy-row mapping/import and shadow comparison.
- Not implemented: production discovery wiring, adapters for the other retailers, live retailer validation, live retailer validation and deployment configuration.
- No production database has been read or written, no live retailer request has been made, and no deploy has been performed.
