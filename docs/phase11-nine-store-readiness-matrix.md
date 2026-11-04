# Phase 11 — nine-store migration readiness matrix

**Audit date:** 2026-11-04  
**Scope:** repository connector registry and adapter implementations on `phase5/redis-celery-ingestion-pipeline`.  
**Important:** this is a code-level inventory, not evidence that a retailer account is authorized, a live feed is reachable, a store is active in PostgreSQL, or offers are currently published.

## Current connector inventory

The runtime registry constructs nine connectors. Discovery for the eight page/search-based stores requires explicit terms in `SCENTHUNTER_DISCOVERY_TERMS_JSON`; the registry does not invent discovery queries. Notino uses its affiliate feed as its discovery source.

| Store | Runtime key | Current adapter/source shape | Current code-level notes | Phase 11 operational status |
|---|---|---|---|---|
| Notino | `notino` | Authorized CJ/VIV XML affiliate feed | Dedicated feed connector; parses feed evidence and preserves raw XML bytes; requires CJ/VIV entitlement and protected credentials | **BLOCKED** — publisher application pending; no feed entitlement/credentials/live offer verified |
| Deloox | `deloox` | JSON-LD / HTML | Dedicated connector; search terms required; product-page loader optional; browser fallback not enabled | **NOT VERIFIED** — contract exists; no live offer/refresh proof in Phase 5 |
| Easycosmetic | `easycosmetic` | Product-page JSON-LD / HTML | Dedicated connector; search terms required; selected-variant price/stock parser; page loader optional | **NOT VERIFIED** |
| Sabina | `sabina` | Product-page parser / HTML with variant mapping | Dedicated connector; maps product and variant rows; search terms required; page loader optional | **NOT VERIFIED** |
| Parfumzentrum | `parfumzentrum` | Product-page JSON-LD / HTML | Dedicated connector; search terms required; page loader optional; EUR assigned by adapter | **NOT VERIFIED** |
| PerfumeMarket | `perfumemarket` | Shopify / JSON-LD legacy parser | Uses shared `LegacyStoreConnector`; discovery terms and optional page loader | **NOT VERIFIED** |
| ParfumCity | `parfumcity` | Shopify search with parsed product/variant rows | Uses shared `LegacyStoreConnector`; search already returns parsed variants; no public page parser wired | **NOT VERIFIED** |
| Bplatz | `bplatz` | Shopify JSON-LD product parser | Uses shared `LegacyStoreConnector`; separate legacy Phase 2 Liquid Brun persistence proof exists, but it is not Phase 5 proof for other products | **PARTIAL** — legacy proof only; Phase 5 offer ingestion and refresh still unproven |
| Orioudh | `orioudh` | Shopify product JSON parser | Uses shared `LegacyStoreConnector`; discovery terms and optional page loader | **NOT VERIFIED** |

## What the current evidence does and does not prove

- **Proven at code level:** all nine keys are registered in the Phase 5 runtime registry.
- **Proven at CI infrastructure level:** PostgreSQL migrations/seed and a real Redis/Celery worker smoke are exercised in disposable CI, as documented in PR #343.
- **Not proven:** nine active store rows, nine successful live discovery runs, published offers from each store, per-store price/stock refresh, or production traffic readiness.
- The Phase 5 runtime integration test intentionally asserts zero refresh jobs and zero configured stores and does not contact retailers. The canonical seed reports zero imported offers. Therefore it cannot be used as a live-store acceptance test.
- Notino is additionally blocked by pending CJ publisher approval. Do not substitute a public page scrape or another retailer feed for the authorized feed path.

## Required acceptance gates — repeat independently for every store

A store is eligible for Phase 11 shadow-read comparison only after all relevant checks below have evidence attached to a run/PR:

1. **Authorization and source**
   - Confirm permitted access method and any account/feed entitlement.
   - Record source type (API/feed, structured page data, HTML); do not use browser automation unless explicitly justified as last resort.
   - Confirm allowed hostnames, country, currency, terms of use, request limits and rate limit.
2. **Connector contract**
   - Discovery returns stable retailer product IDs and canonical product URLs.
   - Product fetch and offer fetch use the same connector instance/cache semantics.
   - Price/stock refresh returns a fresh observation for the same external offer identity.
   - Raw source evidence is retained safely with content type, capture time and checksum.
3. **Data quality**
   - Price is positive and currency is explicit/ISO.
   - Availability is explicit; unknown/preorder remains unpublished unless canonical policy explicitly supports it.
   - Product URL is HTTPS and on the approved retailer host.
   - Brand, fragrance, concentration, size and variant are unambiguous.
   - Exact GTIN/SKU/canonical match or manual review; ambiguous match never auto-publishes.
4. **Isolation and resilience**
   - Store is explicitly provisioned and activated; no implicit activation by seed.
   - Connector failure/quarantine does not stop another store's queue.
   - Retry/backoff, rate limiting, dead-letter and reprocessing are tested.
   - Store can be disabled independently without affecting search or other stores.
5. **End-to-end evidence**
   - One real, permitted offer is ingested into isolated staging PostgreSQL.
   - Offer is read back in a new DB session with exact variant/store/URL/price/currency/availability/timestamp.
   - Celery refresh is consumed by a worker and the updated observation/price history is persisted.
   - Ordinary user search reads the stored/indexed offer and makes **zero synchronous retailer requests**.
   - Sanitized CI/run IDs, task IDs and counts are attached to the evidence.

## Phase 11 rollout eligibility

Do not assign equal traffic percentages to stores just because all connectors are registered. Readiness is evaluated per store, but user-facing canary routing is evaluated for the complete search response and the exact set of stores/markets included in that release.

- **0% new API / legacy serves users:** current state.
- **Shadow mode:** only after the selected pilot has real staging offers and the complete Gate 0/rollback prerequisites are met.
- **5% → 20% → 50% → 100%:** only after each previous stage meets the thresholds and has an approved report.
- Keep legacy search available as rollback during the agreed stabilization window.
- Do not retire live search or legacy scrapers until a separate decommission decision and PR.

## Work sequence

1. Finish the architecture/planning document and agree the full store/country scope.
2. Close the Notino authorization dependency separately; do not block code-level work on the other eight.
3. Select the first *authorized and operationally accessible* non-Notino pilot if Notino remains pending. Bplatz has prior legacy evidence, but must still pass the Phase 5 PostgreSQL/Celery acceptance test; it is not automatically approved.
4. Run the acceptance checklist for one store at a time, starting with the most structured and reliable permitted source.
5. Only after one pilot proves the full path, expand to the remaining stores and then consider Phase 11 shadow mode.

## Current decision

**Phase 11 remains BLOCKED at Gate 0.** This matrix improves scope visibility; it does not change traffic, activate stores, run live scrapers, seed offers, deploy workers, or authorize a merge.
