# Phase 11 — affiliate-feed alternatives (2026-11-05)

## Purpose

Find a permitted product-data source for the first genuine catalog-first offer without relying on retailer HTML scraping. This is a research shortlist, not authorization to fetch feeds or activate retailers.

## Candidate sources

| Network / advertiser | Publicly documented feed evidence | What remains unverified |
|---|---|---|
| CJ / NOTINO.fr | CJ/VIV previously confirmed an XML product feed for approved Notino.fr publishers, with product identity, EAN/GTIN, URL, price, currency, availability and images; daily updates. | NOTINO.fr application is still pending in the publisher account. No feed credentials or entitlement. Do not fetch. |
| Awin / Perfume Market UK (merchant 124168) | Public Awin merchant profile advertises an automated product feed updated daily. | Publisher acceptance, feed visibility/download entitlement, exact fields, shipping destinations, and permission for price-comparison use. |
| Awin / Perfumetrader DE (merchant 11672) | Public Awin merchant profile advertises product data. | Publisher acceptance, feed visibility/download entitlement, exact fields, shipping destinations, and permission for price-comparison use. |
| Rakuten / The Fragrance Shop (merchant 43488) | Retailer affiliate page advertises a fully automated daily product feed. | Publisher acceptance, feed access, exact fields, shipping to target countries, and whether its UK-only catalog is useful to ScentHunter. |

## Awin account verification — 2026-11-06

The ScentHunter publisher account (publisher ID 3021971) was checked in **Toolbox → Create-a-Feed → Select advertiser**. The search for `Perfumemarket` returned “No results found” with the France region filter removed. A second search for `Perfumetrader` also returned no results (user-confirmed). Therefore neither candidate is currently selectable in this account's Create-a-Feed advertiser picker. This does not prove the advertisers do not exist on Awin globally; it means the previously identified public merchant leads are not usable through this account's current feed picker.

Do not spend further time retrying these two names in this picker unless account/program status changes. Do not generate an API token solely to resolve this: the current evidence is advertiser visibility, not an API authentication failure.

## Awin feed access notes

Awin's publisher documentation describes:
- Product-feed list downloads showing advertiser, feed, language, last update, joined status and download URL.
- Standard CSV/Create-a-Feed access through Toolbox.
- An Enhanced/Google JSONL feed API for publishers with the appropriate access.
- Feed fields may be unmapped or empty; actual source completeness must be measured, not assumed.

Do not place Awin API keys, feed URLs containing secrets, or credentials in repository files, issues, comments, logs, or chat.

## Immediate account-side action

In the Awin publisher account:
1. Open Advertisers / Join programmes and search for 'Perfume Market' and 'Perfumetrader'.
2. Check whether either program is available for application and submit only if its terms accept product-comparison / price-comparison publishers.
3. Open Toolbox → Create-a-Feed (or the product-feed list) and check whether a feed is visible after joining or under pre-join access.
4. Record only non-secret facts: advertiser ID, program status, feed name/locale, last update, and whether columns exist for product URL, product name, brand, price, currency, availability, EAN/GTIN, and product/variant ID.
5. Confirm shipping coverage and the program's permitted use before connecting anything.

## Connector implementation gate

Do not implement a live Awin downloader against guessed endpoints or sample data. Once an approved feed is actually visible, obtain a small sanitized sample with credentials and tracking tokens removed. Then build a feed-specific adapter and fixture tests for:
- CSV/JSONL parsing and locale-specific numeric prices;
- explicit ISO currency (missing/malformed stays unknown);
- explicit stock mapping (unknown stays unknown);
- stable advertiser product/variant IDs and GTIN;
- product URL host validation and affiliate deep-link preservation;
- updated timestamp / stale-feed rejection;
- duplicate handling and canonical matching;
- no network access in parser tests.

## Gate 0 status

**BLOCKED.** No Awin advertiser has been approved or feed entitlement verified. No feed was downloaded. No retailer was activated. No live retailer request was made. Awin is an additional route to investigate, not a substitute for authorization.

Notino CJ remains pending; Bplatz permission remains unanswered; Deloox's previous HTTP 403 remains a blocker. Shadow and canary remain at 0%.
