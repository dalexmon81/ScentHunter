# Phase 11 — Bplatz candidate pilot readiness

**Audit date:** 2026-11-05  
**Branch reviewed:** `phase5/redis-celery-ingestion-pipeline`  
**Decision:** candidate for a controlled staging pilot, **not yet approved for execution or traffic**.

This is a source-code review only. No request was sent to Bplatz, no store was activated, no staging database was changed, and no offer was created.

## Why Bplatz is the next candidate to assess

- The repository contains a dedicated `BplatzConnector` registered under runtime key `bplatz`.
- It wraps the existing Bplatz scraper through `LegacyStoreConnector`.
- A previous Phase 2/legacy proof for a Bplatz Liquid Brun fixture is documented in the Phase 11 Gate 0 audit. That proves a legacy persistence path for that fixture only; it does not prove Phase 5 PostgreSQL/Celery ingestion.
- Unlike Notino, this candidate is not dependent on the pending CJ publisher application. However, the permitted access method, current retailer terms, and operational reachability still need to be confirmed before a live request.

## Code path inspected

### Connector construction

`backend/app/connectors/runtime_registry.py` registers:
- `"bplatz": BplatzConnector(terms.get("bplatz", ()))`

Discovery terms are supplied explicitly through `SCENTHUNTER_DISCOVERY_TERMS_JSON`. No discovery term is automatically invented when none is configured.

### Adapter

`backend/app/connectors/bplatz.py` creates a `LegacyStoreConnector` with:
- store key `bplatz`;
- scraper `scrapers.bplatz.scraper`;
- product page parser `scraper.product_from_page`;
- optional configured discovery terms.

The shared adapter:
- maps the scraper's structured result into `OfferRecord`;
- captures raw product-page response bytes when the parser uses its session;
- exposes `discover_products`, `fetch_product`, `fetch_offers` and `fetch_price_and_stock`;
- validates the normalized offer contract;
- does not write to the canonical database itself.

### Source parser

`backend/scrapers/bplatz/scraper.py`:
- uses `https://en.bplatz.de`;
- has bounded timeouts and candidate/page limits;
- discovers candidate product URLs through Shopify predictive search, search JSON, products JSON, sitemap and HTML search fallbacks;
- fetches the product page and parses Product/ProductGroup JSON-LD;
- extracts title, brand, SKU and GTIN only when present in structured product data;
- derives size and concentration from the product page;
- extracts price and availability from JSON-LD and page text;
- treats explicit unavailable/sold-out signals before positive availability signals;
- leaves missing SKU/GTIN absent rather than fabricating identifiers.

## Risks and gaps to resolve before a live pilot

1. **No live Phase 5 retailer proof:** Phase 5 CI now proves the Bplatz connector path against a synthetic, local fixture, including canonical matching, offer promotion, price history and refresh behavior. It still does not call Bplatz, use a retailer-authorized source response, or persist a real retailer offer in persistent staging.
2. **Historical evidence is a different path/product:** the earlier Liquid Brun proof is not evidence for the new PostgreSQL/Celery path and must not be represented as a Dior result.
3. **Variant identity:** the parser emits product-level data and may not expose a stable retailer variant ID. The canonical matcher must resolve exact fragrance, concentration and size; ambiguous or incomplete identity stays unpublished.
4. **Availability quality:** unknown availability is represented as unknown and must not be promoted. Only explicit supported states may pass canonical promotion.
5. **Identifier quality:** missing SKU/GTIN must remain missing. Do not use a product URL as a fabricated GTIN or claim it is a retailer variant identifier.
6. **Source/access review:** confirm the retailer's current permitted automated access method, terms and rate limits before enabling any live discovery. Do not bypass blocks or access controls.
7. **Refresh behavior:** prove that refresh reloads the same product page and updates the same offer identity, without creating duplicates or doing any retailer request during normal user search.
8. **Error handling:** distinguish verified empty search results from blocked, timed-out or unavailable source responses; ensure one Bplatz failure cannot block other store queues.

## Controlled acceptance plan

### Gate B1 — fixture-only contract tests (no network)

**Partial PASS — core Bplatz fixture path and refresh regression are covered by CI; the full checklist below is not yet proven.**

Evidence on Phase 5 branch commit `b853faa41514952aeab3a996c396725c64d0493b`:
- Phase 4 connector contract: **111 passed** (run `41965059287`), including expanded Bplatz price, size/concentration and variant-conflict tests.
- Phase 5 ingestion tests: **53 passed** (run `41965059301`); runtime integration succeeded, confirming Redis broker, Celery worker consumption, PostgreSQL task query, durable dead-letter write, canonical seed, and `SAFE_NO_RETAILER_NETWORK_CALLS=PASS`.
- Added a store-isolated quarantine test and a local page-loader raw-HTML capture assertion. These are fixture/unit tests, not live retailer evidence.
- The negative-price guard rejects a leading minus sign before numeric extraction; parser tests cover valid EUR formats, zero/negative/out-of-range prices, size/concentration parsing, explicit in-stock/out-of-stock, and conservative handling of preorder/unknown.
- The Bplatz synthetic HTML fixture has no fabricated SKU or GTIN; absent identifiers remain absent and the product URL is used only as the external ID fallback.
- The local end-to-end fixture test exercises `run_connector_once`, exact Dior Sauvage EDP 100 ml canonical matching, promotion in an in-memory SQLite test database, active-offer readback, EUR price, stock, PriceHistory and MatchAudit. This is a test fixture, not retailer evidence or persistent staging.
- Refresh regression tests cover Bplatz alongside PerfumeMarket, ParfumCity and Orioudh, verifying that a fresh page observation updates the same offer identity rather than retaining the stale price.
- Phase 5 commit `4e91f35e2ef9ef3bc5372985863a12173983200f` adds an ingestion-task integration test proving original HTML bytes are persisted in `ingestion_artifacts`, SHA-256 and byte length are recorded, the artifact is linked to its `ingestion_run`, and the staged offer references that artifact ID. Phase 4 passed; Phase 5 pipeline and runtime-integration jobs both passed (run `41966249659`). This remains a synthetic fixture test using SQLite; it is not a live Bplatz fetch or a persistent staging offer.

Remaining B1 checks (do not infer they passed from the aggregate CI totals):
- [ ] Separate positive-stock, sold-out and unknown-stock Bplatz fixture matrix.
- [ ] Full invalid/missing/zero-price rejection matrix for Bplatz.
- [ ] Multiple concentration/size parsing matrix and explicit wrong-size/ambiguous-match cases.
- [ ] Raw HTML artifact capture assertions for the Bplatz path.
- [ ] Explicit retry/quarantine isolation test for a Bplatz source failure.

### Gate B2 — isolated staging one-offer vertical slice

Only after B1 passes and access is approved:
1. Confirm separate staging PostgreSQL and Redis.
2. Provision the Bplatz store explicitly in staging; do not silently activate it from the general catalog seed.
3. Select one exact canonical product/variant for which the Bplatz page has clear evidence. Do not assume Liquid Brun or Dior is available.
4. Run one bounded discovery/fetch through the Bplatz connector.
5. Persist source evidence, ingestion run and staged offer.
6. Verify exact brand/fragrance/concentration/size mapping.
7. Promote only if URL, positive EUR price, explicit availability, timestamp, store status and exact match pass.
8. Read the published offer back in a new DB session and verify its exact variant/store/external identity.
9. Enqueue one Celery refresh; verify the same offer is updated and price history is recorded without duplicates.
10. Run an ordinary catalog search and prove it reads the stored/indexed offer with zero synchronous Bplatz requests.
11. Attach sanitized run IDs, task IDs, counts and evidence to the Phase 11 PR.

### Gate B3 — shadow-read eligibility

Bplatz can be included in Phase 11 shadow mode only after B2 passes and the wider Phase 11 Gate 0 requirements, monitoring, kill switch and rollback are also verified.

A successful Bplatz pilot alone does not authorize 5% user traffic or prove readiness of the other eight stores.

## Current status

| Gate | Status |
|---|---|
| Connector registered | PASS |
| Adapter and scraper code reviewed | PASS |
| Legacy Phase 2 persistence proof | PARTIAL; legacy-only, Liquid Brun fixture |
| Fixture contract test evidence for this audit | PARTIAL PASS — synthetic fixture E2E + refresh regression in CI |
| Live source authorization/terms review | NOT VERIFIED |
| Phase 5 staging store provisioned | NOT VERIFIED |
| Real offer persisted in Phase 5 PostgreSQL | NOT RUN |
| Celery refresh and price-history readback | NOT RUN |
| Search performs no synchronous retailer request | Requires end-to-end proof |
| Phase 11 shadow/canary | BLOCKED |

**Safe next action:** complete the remaining B1 fixture matrix and source-access review. Only then consider one bounded B2 staging run, after isolated staging and explicit retailer-access approval are confirmed. No live request or staging write has been performed.
