# Phase 11 — alternative retailer feed shortlist

**Research date:** 2026-11-05  
**Purpose:** identify a permitted, feed-first retailer pilot that can proceed independently of the pending Bplatz permission request.

## Decision rule

Do not activate a retailer merely because it has an affiliate programme. Before implementation, confirm all of the following in the authenticated publisher account or in writing with the advertiser/network:

1. The programme accepts ScentHunter's business model (price comparison / product discovery).
2. A product feed or documented API is actually enabled for this publisher and target country.
3. Feed terms permit ingestion, normalization, storage, price/stock display, refresh frequency, and affiliate deep links for this use.
4. Feed fields include a stable product identifier (EAN/GTIN preferred), product URL, price, currency, availability, and update timestamp or documented refresh cadence.
5. Country delivery restrictions and shipping scope are suitable for the intended ScentHunter markets.

An affiliate link or approval alone is not permission to scrape the retailer website. No live retailer requests or feed downloads were made during this research.

## Ranked candidates

| Priority | Retailer / network | Public feed evidence | Why it is worth checking | Remaining blockers |
|---|---|---|---|---|
| 1 | BeautyTheShop FR — Awin | Awin merchant profile describes 12,000+ products, 25-country reach, and a product feed that is regularly updated. | French-facing perfume specialist with niche and luxury fragrances; potentially useful for France/Luxembourg coverage. | Apply/confirm publisher acceptance; obtain feed access; verify feed schema, countries, stock fields, refresh cadence, and data-use rights. |
| 2 | Paco Perfumerías — Awin | Awin merchant profile explicitly advertises a **Daily Product Feed**. | Large Spanish perfumery catalogue; concrete documented feed and strong fragrance relevance. | Confirm programme territory and publisher approval; verify whether the feed is available to this account and whether shipping serves target countries. |
| 3 | ParfumGroup DE — Awin | Awin profile says a regularly updated product data feed is available. | German retailer is geographically relevant to Luxembourg; fragrance-led assortment. | Confirm publisher acceptance, actual feed access, feed field completeness, target-country shipping and permitted comparison use. |
| 4 | Douglas NL — Awin | Douglas NL programme page advertises a daily-updated datafeed and says the feed meets its requirements. | Nearby Benelux market and a broad beauty catalogue. | Confirm the exact programme/feed is accessible to this publisher and whether it includes fragrance stock, EAN, price, currency, and Luxembourg delivery. |
| 5 | Notino — CJ | Notino's official affiliate pages route partners through CJ; CJ's Product Feed API supports product-feed summary and product detail queries for joined and non-joined advertisers, subject to API credentials and advertiser/company IDs. | Large European fragrance catalogue; existing ScentHunter integration planning already considered Notino. | Staging previously reported CJ feed credentials absent. Confirm publisher relationship, Notino feed availability, API token/company IDs, and use rights before implementation. |
| 6 | Perfumería Comas FR/ES — Awin | Awin programme profiles confirm affiliate programmes and broad perfume assortments; public profile evidence reviewed here does not establish a product feed. | Specialist fragrance retailer with France/Spain programme coverage. | Lower priority until the advertiser confirms an actual product feed or API and approves the intended use. |

## Source links

- BeautyTheShop FR Awin profile: https://ui.awin.com/merchant-profile/101551
- Paco Perfumerías Awin profile: https://ui.awin.com/merchant-profile/21605
- ParfumGroup DE Awin profile: https://ui.awin.com/merchant-profile/73127
- Douglas NL affiliate programme (daily datafeed): https://www.douglas.nl/nl/cp/affiliate-partnerprogramm/affiliate-partnerprogramm
- Notino FR affiliate programme: https://www.notino.fr/programme-affiliation/
- CJ Product Feed API documentation: https://docs.cj.com/docs/productfeed-api-search
- Perfumería Comas FR Awin profile: https://ui.awin.com/merchant-profile/105475

## Recommended next action

Start with **BeautyTheShop FR** and **Paco Perfumerías** in the Awin account: verify whether their feeds are available to the publisher and download only through the network's authorized feed/API mechanism. In parallel, check ParfumGroup DE for Luxembourg delivery. Do not write a scraper or activate any store until the feed terms and actual account permissions are confirmed.

If none of these feeds is accessible, request written confirmation from the advertiser/network rather than falling back to live HTML scraping.

## Status

Research only. No programmes joined, no credentials accessed, no feeds downloaded, no retailer activated, and no live store requests made. Gate 0 remains BLOCKED; shadow/canary remain 0%.
