# Offer Platform v1 — Implementation Plan

This plan is deliberately gated. Each phase must produce evidence before the next one begins.

| Phase | Deliverable | Exit condition |
|---|---|---|
| 0. Baseline | Anchor product fixture file, current search captures, retailer matrix | Reproducible baseline with exact URLs, size, concentration, price, stock and timestamp |
| 1. Contracts | Adapter protocol, market configuration, result-state enum, observation schema | Contract tests cover every status and malformed input |
| 2. Vertical slice | One retailer end-to-end through acquisition, evidence, parser, matcher, persistence and read API | Live page verified repeatedly; exact product/variant and URL correct |
| 3. Reliability | Per-retailer scheduling, bounded concurrency, timeout/circuit breaker, last-known-good state | Forced failure of one adapter cannot delay or erase other offers |
| 4. Retailer expansion | Remaining retailers added independently | Each adapter has fixture tests and live canary evidence |
| 5. Shadow | New read model compared to stable search without publication | Identity precision and coverage thresholds met |
| 6. Canary | Small, reversible production exposure | Monitoring and rollback verified |
| 7. Cutover | Replace only the relevant search read path | Explicit approval and documented rollback |

## Initial retailer matrix

| Retailer/market | Existing code | First validation focus |
|---|---|---|
| Bplatz / DE | `backend/scrapers/bplatz` | exact variant, price and stock precedence |
| Deloox / BE-NL | `backend/scrapers/deloox` | locale/host selection, size integrity, timeout behavior |
| Easycosmetic / DE | `backend/scrapers/easycosmetic` | variant selection and price freshness |
| Sabina / ES | `backend/scrapers/sabina` | duplicate offers and product URL |
| ParfumZentrum / DE | `backend/scrapers/parfumzentrum` | hydration and exact variant |
| ParfumCity / NL | `backend/scrapers/parfumcity` | market and stock |
| PerfumeMarket / NL | `backend/scrapers/perfumemarket` | exact product URL and currency |
| Orioudh | `backend/scrapers/orioudh` | repeatable discovery and page validation |
| Notino / FR | `backend/scrapers/notino` | feed credentials vs public fallback; country path |
| Amazon / DE, FR | `backend/scrapers/amazon_de`, `amazon_fr` | approved API credentials, ASIN and marketplace |

Market labels above are starting configuration hypotheses from current code, not proof that every locale is the correct one for every customer. Confirm canonical host and shipping market from real product pages before publishing.

## Anchor fixture requirements

Every fixture must contain:
- canonical product ID and canonical variant ID;
- expected brand, product name, edition, concentration and size;
- retailer and market;
- exact retailer product URL;
- expected currency and a manually verified price snapshot;
- expected stock state and evidence text/field;
- source capture time and parser version.

Minimum anchors:
1. Liquid Brun, standard, 100 ml.
2. Liquid Brun Limited Edition, 150 ml.
3. Born in Roma variants selected to exercise different concentrations and sizes.

The Bplatz Liquid Brun Limited Edition 150 ml observation is a negative-stock regression fixture. It must never be upgraded to in-stock from a generic page-level signal when the selected variant is unavailable.

## Decisions still requiring measurement

- Keep SQLite for the first single-machine vertical slice or move the write path to managed Postgres: decide from write contention, durability and worker topology measurements.
- Which external extraction provider, if any, improves content-verified success on the exact perfume retailer URLs at an acceptable cost.
- Which refresh interval is appropriate for each retailer based on price/stock volatility and rate limits.
- Whether browser execution is needed per retailer or only for a small blocked subset.

## Definition of done

A phase is complete only when its code, tests, run evidence, known failures and rollback behavior are committed. A green unit-test workflow by itself does not complete a live retailer integration.
