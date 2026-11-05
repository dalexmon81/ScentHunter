# Phase 11 — audit of the nine existing retailers

**Audit date:** 2026-11-05  
**Branch:** `phase11/gradual-migration`  
**Scope:** repository/code evidence and previously recorded bounded live-probe evidence. This is not a fresh live test of all nine stores.

## Executive result

The nine retailer integrations exist in the legacy scraper layer and are registered in the Phase 5 connector work, but that does **not** mean nine production-ready catalog-first connectors are active. The isolated staging deployment currently reports `stores=0`, `offers=0`, and `invalid_active_offers=0`. No retailer is activated in staging.

A code path, parser fixture, HTTP 200, or a successful CI workflow is not proof of:
- current retailer permission for automated collection;
- a live feed/API entitlement;
- correct price, currency, stock and variant extraction across products;
- a real offer persisted and refreshed by Celery;
- an end-to-end catalog-first search result.

## Store-by-store status

| Store | Repository evidence | Existing technical evidence | Current blocker / next action |
|---|---|---|---|
| **Bplatz** | Legacy scraper plus bounded manual-only Phase 5 ingestion task, merged in PR #360 and deployed to staging. | Offline fixture and validation tests passed; task has not been invoked. | Written permission/API/feed request sent to Bplatz; no reply. Keep inactive until permitted method is confirmed. |
| **Deloox** | Legacy scraper module exists; Phase 5 connector registration is included in the pipeline work. | A previous bounded direct URL probe recorded HTTP 403. | Do not retry around the block. Ask retailer/network for permitted feed/API or written permission; then validate the official route and parser. |
| **Easycosmetic** | Legacy scraper module exists; Phase 5 connector registration is included in the pipeline work. | Previous bounded probe recorded HTTP 200 for one known page but no Product JSON-LD. This does not establish parser success or failure across the site. | Inspect the current permitted data source and page format; add representative fixtures for price, stock, EAN, variants and unavailable products. |
| **Notino** | Legacy scraper module exists; separate CJ affiliate-feed route is documented. | CJ confirms XML feed exists for approved publishers. User's CJ screenshot shows advertiser 4912189 in Pending Applications. | Await Notino approval. After approval, verify feed entitlement, terms, credentials and schema; prefer the official feed over scraping. |
| **Orioudh** | Legacy Shopify-oriented scraper module exists; product JSON endpoint handling is present in code. | Code parses Shopify product JSON and variant prices; no current authorized-feed entitlement or current end-to-end staging evidence recorded. | Confirm permitted API/feed route and terms; fixture-test integer-cent prices, variant IDs, GTIN, stock and canonical variant matching. |
| **ParfumCity** | Legacy scraper module exists; retailer base URL and bounded candidate discovery are defined. | Code-level parser/discovery only in the evidence reviewed for this audit. | Confirm permitted feed/API or written terms; create representative parser fixtures and test price/stock/variant extraction. |
| **ParfumZentrum** | Legacy scraper module exists; parser and sitemap/search discovery are implemented. | Strongest current evidence: offline parser tests cover JSON-LD price, availability and placeholder-price rejection (`backend/tests/test_parfumzentrum_hydration.py`); captured live output is covered by `tests/test_live_retailer_identity_resolution.py`, including exact 125 ml GTIN-to-variant mapping and fail-closed conflicts; a prior bounded probe recorded HTTP 200 and `adapter_status=parsed`. | Permission and a real Phase 5 persisted offer/refresh/search path remain unproven. Verify access terms and repeat through isolated staging only after approval. |
| **PerfumeMarket** | Legacy scraper module exists; Shopify-style product/card parsing is present. | Previous bounded probe recorded HTTP 200 for one page. That response alone does not prove successful structured product extraction. | Confirm permitted API/feed or written terms; add fixtures and verify GTIN, variant, price, currency, availability and canonical match. |
| **Sabina** | Legacy scraper module exists; code includes native search, Sellboost search endpoint and a bounded browser fallback. | The implementation has multiple discovery paths, but this audit has no current end-to-end Phase 5 offer evidence. | Confirm terms and permitted API/feed route. Review the third-party search endpoint and browser fallback against the retailer/network's conditions; test stock and variant correctness. |

## Important distinction: code versus authorization

Several existing scrapers use direct HTTP, retailer search pages, sitemaps, Shopify-style JSON endpoints, or browser automation. Their presence in the repository is not itself authorization to automate access. Do not activate a store, download a feed, or schedule live refresh until the permitted method and applicable terms are confirmed.

The Notino CJ application is pending, not approved. Bplatz has an unanswered permission request. For the other seven stores, this audit has not established written permission, an enabled affiliate feed, or a documented API entitlement. Treat their authorization status as **unverified**, not as denied and not as approved.

## Existing automated test coverage found during this audit

- **ParfumZentrum:** retailer-specific offline HTML/JSON-LD parser tests and captured-live-output canonical GTIN/variant matching tests exist. These are meaningful regression tests, but do not fetch the retailer or write a real offer.
- **Deloox:** URL admission, search budget/deadline, and parser regression tests exist. A previous live probe still recorded HTTP 403; passing offline tests do not remove that access blocker.
- **Easycosmetic:** generic hydration timeout and deduplication tests exist, but this audit did not locate a comparable retailer-specific end-to-end fixture suite proving full product/offer extraction.
- **PerfumeMarket, Orioudh, ParfumCity, Sabina and Notino:** scraper code exists, but this audit did not locate sufficient retailer-specific contract tests proving the complete normalized offer contract end to end.
- **Bplatz:** bounded ingestion fixture/authentication tests exist for the manual-only pilot; the task has not been invoked.

A missing test found by this search is recorded as “not located in the reviewed paths”, not proof that no test exists anywhere in the repository.

## What has been verified in Phase 5 staging

Successful isolated Fly.io staging deployment: [workflow 42085586218](https://github.com/dalexmon81/ScentHunter/actions/runs/42085586218).

- 60 brands, 1,389 fragrances and 512 variants seeded.
- One non-root Celery app worker; zero Beat machines.
- Alembic migrations applied; broker ping and queued task smoke passed.
- No retailer activated: `stores=0`.
- No offers imported: `offers=0`.

This is infrastructure readiness only. It is not a nine-store integration test.

## Required audit sequence

1. For each retailer, record the exact allowed access mechanism: official API, merchant feed, affiliate-network feed, or written permission. If no permitted mechanism is confirmed, mark it `blocked_authorization` and do not call it.
2. Build a connector contract test from saved, permitted fixtures. Required normalized fields: store ID, external product/variant ID, product URL, title, brand, EAN/GTIN when available, size, concentration, price, ISO currency, explicit availability and captured timestamp.
3. Test positive and negative cases: available, unavailable, missing price, malformed currency, wrong size/concentration, duplicate GTIN, redirect/invalid URL, timeout and retailer error.
4. Validate canonical matching conservatively. Ambiguous products must go to review; never auto-publish based on name similarity alone.
5. Activate only one approved store in isolated staging. Import one genuine offer and prove PostgreSQL persistence, validation, Celery refresh, price history, and catalog-first search with no synchronous retailer request.
6. Repeat per store only after the first vertical slice passes. Keep failures isolated and quarantine the affected connector.
7. Update the Gate 0 checklist only with reproducible evidence. Do not enable shadow or canary until the Gate 0 requirements and rollback checks are complete.

## Status

**Nine-store audit: code inventory completed; authorization and end-to-end readiness remain unverified for most stores.**  
**Gate 0: BLOCKED. Shadow/canary: 0%.**  
No production changes, live retailer requests, feed downloads, or retailer activation were performed by this audit.
