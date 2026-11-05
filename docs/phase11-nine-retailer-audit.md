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
| **Deloox** | Legacy scraper module exists; Phase 5 connector registration is included in the pipeline work. | Previous bounded direct URL probe recorded HTTP 403. The parser now preserves currency only from an explicit three-letter code on the selected structured Offer or its priceSpecification; absent/malformed currency remains null. Three offline regressions cover missing currency, explicit priceSpecification currency and malformed currency. Parser commit `32eb356cb5e9d85c8d0c9d1a394b9d0036a373d8`; tests commit `f23f183b7eb10d41ec2ef939bd8d2f8214cf5c33`; CI pending. | Do not retry around the block. Ask retailer/network for permitted feed/API or written permission; then validate the official route and parser. |
| **Easycosmetic** | Legacy scraper module exists; Phase 5 connector registration is included in the pipeline work. | Previous bounded probe recorded HTTP 200 for one known page but no Product JSON-LD. This does not establish parser success or failure across the site. | Inspect the current permitted data source and page format; add representative fixtures for price, stock, EAN, variants and unavailable products. |
| **Notino** | Legacy scraper module exists; separate CJ affiliate-feed route is documented. | CJ confirms XML feed exists for approved publishers. User's CJ screenshot shows advertiser 4912189 in Pending Applications. | Await Notino approval. After approval, verify feed entitlement, terms, credentials and schema; prefer the official feed over scraping. |
| **Orioudh** | Legacy Shopify-oriented scraper module exists; product JSON endpoint handling is present in code. | Code parses Shopify product JSON and variant prices; no current authorized-feed entitlement or current end-to-end staging evidence recorded. | Confirm permitted API/feed route and terms; fixture-test integer-cent prices, variant IDs, GTIN, stock and canonical variant matching. |
| **ParfumCity** | Legacy Shopify-oriented scraper; bounded discovery and per-variant extraction are implemented. | Offline tests now exercise `make_item()` output: product/variant IDs, barcode-to-GTIN, size, price and explicit stock. Assumed EUR removed; missing currency remains unknown. Hardening `539ef8f41ead15f5b7086424ebfc8d8d4b05d9a2`; tests `1c2d1919bfc0e17367e7efd91c2a5c5da538ec1d`. | Confirm permitted feed/API or written terms; verify currency from an authoritative source before publishing; end-to-end persistence/refresh/search remains unproven. |
| **ParfumZentrum** | Legacy scraper module exists; parser and sitemap/search discovery are implemented. | Existing offline tests cover JSON-LD price, availability and placeholder-price rejection. New adapter-level contract tests cover GTIN/SKU/size, explicit currency, missing/malformed currency, out-of-stock without price, and retailer-domain URL validation. Currency is now taken only from a three-letter `priceCurrency` value explicitly present in structured offers; it is no longer hardcoded to EUR. Commits: parser `67cb66831400b046c5fc2ff7199540c7a29c842f`; tests `20d5187530adfe9c297663b60760036dd5fc3282`. Prior bounded probe recorded HTTP 200 and `adapter_status=parsed`; that is not authorization or end-to-end proof. | Permission and a real Phase 5 persisted offer/refresh/search path remain unproven. Verify access terms and repeat through isolated staging only after approval. |
| **PerfumeMarket** | Legacy scraper module exists; Shopify-style product/card parsing is present. | Previous bounded probe recorded HTTP 200 for one page. That response alone does not prove successful structured product extraction. | Confirm permitted API/feed or written terms; add fixtures and verify GTIN, variant, price, currency, availability and canonical match. |
| **Sabina** | Legacy scraper with native search, Sellboost endpoint and bounded browser fallback. | Offline product-page contract tests cover GTIN, price, currency and availability. Implicit EUR defaults removed; currency remains unknown unless structured source data supplies it. Hardening `e0d0859005e0f42488b57a133aa8855ca5ee0c5a` and `2511a2d6c5fc666ea00c7fcb145d09e6289f1212`; tests `1c2d1919bfc0e17367e7efd91c2a5c5da538ec1d`. | Confirm permitted API/feed route; review third-party search and browser fallback terms; full variant identity and authorized end-to-end ingestion remain unverified. |

## Important distinction: code versus authorization

Several existing scrapers use direct HTTP, retailer search pages, sitemaps, Shopify-style JSON endpoints, or browser automation. Their presence in the repository is not itself authorization to automate access. Do not activate a store, download a feed, or schedule live refresh until the permitted method and applicable terms are confirmed.

The Notino CJ application is pending, not approved. Bplatz has an unanswered permission request. For the other seven stores, this audit has not established written permission, an enabled affiliate feed, or a documented API entitlement. Treat their authorization status as **unverified**, not as denied and not as approved.

## Existing automated test coverage found during this audit

- **Deloox:** adapter-level offline regressions now ensure currency comes only from the selected structured Offer/priceSpecification; absent or malformed currency remains unknown. The existing bounded probe still recorded HTTP 403, so do not attempt a bypass or enable the store. Parser commit `32eb356cb5e9d85c8d0c9d1a394b9d0036a373d8`; tests commit `f23f183b7eb10d41ec2ef939bd8d2f8214cf5c33`; CI pending.
- **ParfumZentrum:** retailer-specific offline HTML/JSON-LD parser tests and captured-live-output canonical GTIN/variant matching tests exist. Added `backend/tests/test_parfumzentrum_offer_contract.py` for the actual adapter output: explicit versus absent/malformed currency, GTIN/SKU/size, explicit out-of-stock with no price, and rejection of a non-retailer URL. The adapter no longer hardcodes EUR. These are offline tests; they do not fetch the retailer or write a real offer. Parser commit `67cb66831400b046c5fc2ff7199540c7a29c842f`; tests commit `20d5187530adfe9c297663b60760036dd5fc3282`; CI status pending at the time of this update.
- **Deloox:** URL admission, search budget/deadline, and parser regression tests exist. A previous live probe still recorded HTTP 403; passing offline tests do not remove that access blocker.
- **Easycosmetic:** added `backend/tests/test_easycosmetic_parser_contract.py` on 2026-11-05. Synthetic offline HTML tests exercise exact `?variant=` JSON-LD selection, prevent borrowing another variant's offer, verify selected-size extraction, ensure the visible product-detail price wins over cached JSON-LD, and preserve explicit out-of-stock state. Follow-up hardening removes implicit EUR defaults: currency is accepted only as an explicit three-letter ISO code in the selected structured offer; absent or malformed values remain `None`. Two adapter-level regressions cover missing and malformed currency. Commits: initial contract tests `4e5a3f86e9168220f6c279d05a1dcd7f790391ea`; parser hardening `66efe09a9cb7ef068f7b1f237de1b9867f686eed`; added tests `23ad087108d59303720afb792294857a63bcd1ed`. CI for the latest commits is pending. These offline tests make no retailer requests and do not prove live authorization or persistence/refresh/search integration.
- **PerfumeMarket, Orioudh, ParfumCity, Sabina and Notino:** scraper code exists, but this audit did not locate sufficient retailer-specific contract tests proving the complete normalized offer contract end to end.
- **Bplatz:** bounded ingestion fixture/authentication tests exist for the manual-only pilot; the task has not been invoked.
- **Orioudh:** added `backend/tests/test_orioudh_perfumemarket_parser_contract.py` on 2026-11-05. Synthetic Shopify `.js` payload tests verify integer-cent price conversion, GTIN/barcode, product/variant IDs, 100 ml and concentration extraction, availability mapping, and rejection of a zero-price variant. These tests do not call Orioudh or establish permission/feed entitlement. A further adapter-level test now invokes `extract_product_page()` itself and verifies the actual returned variant-level contract, including store product/variant IDs, GTIN, size, concentration and stock. Currency is now deliberately `None` because the reviewed Shopify product JSON payload does not expose an ISO currency field; `available` is also `None` when stock is unknown rather than incorrectly becoming `False`. Commits: hardening `d3abd560b8325c1df524aabb75000ab5ccba8c2b`; adapter tests `c2e94338e01af033903adfa2ddfbaed14aebcf53`. CI for the latest commit is not yet reported.
- **PerfumeMarket:** offline tests now cover both the legacy discovery parser and the actual `extract_product_page(session, url, query)` adapter entry point. The adapter test verifies structured brand, SKU, GTIN, numeric price, ISO currency and explicit stock mapping. A negative fixture confirms missing currency remains `None` and missing stock evidence remains `unknown`, even when generic page copy contains the word “Available”. The adapter no longer invents EUR when currency is absent and no longer infers stock from generic page text. Commits: parser hardening `031650dacb1861191c674da0e0c92e8bafcf0473`; contract tests `56a1ae450f71030d20c53c1118066e3d7a01ccae`. CI workflow runs for these new commits were not yet returned at the time of this update; do not treat the new tests as CI-verified until runs complete. The current adapter still does not prove a distinct Shopify variant ID or size/concentration extraction for every page; these must remain unpopulated unless explicit source fields are found.


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

**Nine-store audit: code inventory completed; additional offline parser regressions now cover Easycosmetic, Orioudh, PerfumeMarket, ParfumCity, Sabina and ParfumZentrum, including adapter-level contract checks. The retailer adapters now preserve unknown currency/stock rather than inventing values where source evidence is absent; latest ParfumCity/Sabina CI is pending and authorized end-to-end ingestion remains unverified.**  
**Gate 0: BLOCKED. Shadow/canary: 0%.**  
No production changes, live retailer requests, feed downloads, or retailer activation were performed by this audit.
