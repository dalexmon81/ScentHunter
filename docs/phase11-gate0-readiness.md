# Gate 0 — readiness audit (2026-11-05)

## Decision

**STATUS: BLOCKED — do not start shadow traffic or the 5% canary.**

The selected pilot remains **Bplatz — French Avenue Liquid Brun Eau de Parfum 100 ml**. Notino is now a documented alternative affiliate-feed path, but its application is still pending and it is not yet an active pilot.

This audit distinguishes CI fixtures, staging infrastructure, retailer authorization, affiliate-program approval, and live offer evidence. Passing one category does not imply another.

## Current verified evidence

### Phase 5 staging infrastructure

The isolated Fly.io staging deployment [run 42085586218](https://github.com/dalexmon81/ScentHunter/actions/runs/42085586218) completed successfully. All 20 job steps passed, including isolated ingestion/connector tests, Fly token scope verification and staging secret application, worker deploy with one app worker and zero Beat machines, worker startup and broker connection, read-only database/store safety audit, Alembic migrations, canonical brand-alias normalization, canonical catalog seed without activating a retailer, non-root worker verification, Celery broker ping, and queued-task smoke execution.

The seeded staging catalog contains **60 brands, 1,389 fragrances, and 512 variants**. It reports **stores=0, offers=0, invalid_active_offers=0**. The deployment includes the bounded manual-only Bplatz task from merged PR #360.

This proves staging deployment and smoke execution. It does not prove retailer authorization, a live offer, offer refresh, price history, or end-to-end catalog-first search.

### Bplatz bounded pilot implementation

PR [#360](https://github.com/dalexmon81/ScentHunter/pull/360) added a manual-only task for the exact Bplatz Liquid Brun EDP 100 ml product page. It is restricted to the approved product path, records source evidence against an ingestion run, and passes data through the existing validation/matching/promotion pipeline. It requires an explicit authorization reference.

The offline fixture tests passed in workflow [42073836383](https://github.com/dalexmon81/ScentHunter/actions/runs/42073836383), with 39 tests passing. The task is deployed to staging but **has not been invoked**. The authorization-reference field is a safeguard, not proof that permission exists.

### Bplatz permission request

Bplatz's official [Terms and Conditions](https://en.bplatz.de/pages/purchase-clauses) and [Privacy Policy](https://en.bplatz.de/pages/Data-protection) were reviewed. They do not expressly authorize automated collection or scraping. robots.txt could not be retrieved, so no allow/disallow conclusion is recorded.

A permission request was sent to **orders@bplatz.de** on 2026-11-05. It asks for an approved API/feed/affiliate feed or written permission for a limited one-product test, restricted to product URL, price/currency, and availability. **No reply or authorization has been received yet.** No live Bplatz request has been made.

Do not invoke the task until a permitted access method is confirmed and the authorization reference records the actual approval.

### Notino.fr affiliate program — application pending

The user supplied a screenshot from the CJ publisher account showing advertiser **4912189 — NOTINO.fr**, category **Fragrance**, under the filter **Status: Pending Applications**. The advertiser row is therefore present in the user's pending applications.

The screenshot also shows serviceable area **FRANCE**, supported currency **EUR**, and the program's displayed commission information (default 4–6%; other rates vary by partner type/content). This is evidence of a pending application only — **not approval, active advertiser status, feed entitlement, or permission to scrape Notino's website**.

CJ/VIVnetworks previously confirmed by email that a Notino.fr XML product feed is available to approved publishers and includes product names, EAN/GTIN, direct URLs, current prices, currency, availability, and images, with daily updates. CJ also stated that publisher approval by Notino is required and that Notino makes the final partner decision. The user's CJ network account welcome email confirms network-account activation, not approval to the Notino.fr program.

Next action: wait for the NOTINO.fr application to change from **Pending Applications** to an active/approved status, or for a direct decision from the program. After approval, inspect the program terms and feed access instructions in CJ, confirm the feed's permitted use and technical format, then implement a dedicated feed connector. Until then, do not attempt to fetch the feed or treat Notino as an authorized source.

### Latest retailer parser verification — 2026-11-05

Deloox parser hardening commit `136d381ca44057a2cd0774cc5a4cc6c3764a4720` passed all three relevant CI workflows:
- Backend Parser Regression: [42108328640](https://github.com/dalexmon81/ScentHunter/actions/runs/42108328640)
- Hydration Regression: [42108328805](https://github.com/dalexmon81/ScentHunter/actions/runs/42108328805)
- Next Engine Shadow Integration: [42108328702](https://github.com/dalexmon81/ScentHunter/actions/runs/42108328702)

The fix reads an explicit price from the selected Schema.org `priceSpecification` when `Offer.price` is absent. This is parser/fixture validation only. Deloox's earlier HTTP 403 remains an access blocker; no further live request was made.

The latest Gmail check found no new Bplatz permission response and no Notino advertiser approval/feed entitlement. The CJ network welcome email is not advertiser approval. Therefore these results do not change any Gate 0 authorization or real-offer requirements.

## Awin advertiser application outcomes — verified from Gmail, 2026-11-06

A Gmail search of messages from `no-reply@awin.com` found two advertiser rejection notices dated 2026-08-06 for publisher ScentHunter (PID 3021971):

| Advertiser | Advertiser ID | Recorded rejection reason |
|---|---:|---|
| Fragrance Click UK | 124166 | “Site does not complement advertiser brand” |
| Perfume Click | 6561 | “URL is irrelevant to advertiser brand” |

The same search found the Awin network publisher-account activation email dated 2026-08-05. That account activation is separate from advertiser-program acceptance.

**Scope limitation:** the mailbox search found these two rejection notices; it does not establish that every Awin advertiser application was rejected. The user recalls further applications but no other rejection notices were found in this search. Do not describe all Awin programmes as rejected without additional evidence.

**Interpretation:** both recorded reasons concern perceived site/URL relevance, not API tokens or feed configuration. This suggests improving the public-facing publisher presentation before submitting more applications: clearly explain ScentHunter as a perfume-only search and price-comparison service; show usable perfume category/product pages and genuine, traceable offers; make operator/contact, privacy, terms, affiliate disclosure, data freshness and comparison methodology easy to find. These are recommended readiness checks, not confirmed causes of all advertiser decisions.

Do not reapply to the same advertisers yet. First audit the live public site against those criteria and document the actual pages and current state. No changes to public website or new advertiser applications have been made as part of this audit.

## Additional affiliate-feed route: Awin (research only)

A new research shortlist is documented in [phase11-affiliate-feed-alternatives.md](phase11-affiliate-feed-alternatives.md). Public merchant profiles indicate:
- Perfume Market UK (Awin merchant 124168): daily automated product feed advertised.
- Perfumetrader DE (Awin merchant 11672): product data advertised.
- The Fragrance Shop (Rakuten merchant 43488): automated daily feed advertised.

These public descriptions do not prove publisher acceptance, feed entitlement, price-comparison permission, required fields, or shipping coverage for ScentHunter's target countries. No application result or feed download has been verified. Do not implement a live downloader or activate any of these merchants until the publisher account shows access and the program terms permit the intended use.

## Offline quality evidence

- PR #347 adds the Bplatz offline fixture validation matrix.
- PR #343 workflow [41967935150](https://github.com/dalexmon81/ScentHunter/actions/runs/41967935150) passed Bplatz fixture parsing, Celery discovery, raw artifact SHA-256, and artifact-to-ingestion-run linkage.
- PR #343 workflow [41968439231](https://github.com/dalexmon81/ScentHunter/actions/runs/41968439231) passed timeout retry/quarantine isolation, wrong-size rejection (50 ml versus canonical 100 ml), and ambiguous duplicate-GTIN review without automatic matching.
- Latest PR #345 CI checks passed: backend parser [42074248195](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248195), Next Engine Shadow Integration [42074248249](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248249), and Hydration Regression [42074248330](https://github.com/dalexmon81/ScentHunter/actions/runs/42074248330).

These are offline fixture/stub or CI checks. They are not evidence of a current retailer offer or live authorized ingestion.

## Gate 0 checklist

| Requirement | Status |
|---|---|
| Disposable PostgreSQL/Redis/Celery CI integration | PASS — synthetic CI only |
| Bplatz Liquid Brun historical fixture and validation matrix | PASS — historical/offline only |
| Bplatz artifact linkage and negative-path tests | PASS — fixture/stub CI only |
| Bounded manual Bplatz task implemented | PASS — merged and deployed to staging; not invoked |
| Isolated staging deploy, migrations, canonical seed | PASS — run 42085586218 |
| Staging worker non-root, Celery ping and queued smoke task | PASS — run 42085586218 |
| Bplatz automated access permission/method | BLOCKED — email sent; awaiting reply |
| Notino.fr CJ publisher application | PENDING — screenshot confirms Pending Applications |
| Notino.fr affiliate-feed entitlement | BLOCKED — requires advertiser approval and feed terms review |
| Retailer activated in staging | NOT RUN — stores=0 |
| Real offer persisted through Phase 5 PostgreSQL | NOT RUN — offers=0 |
| Real Celery price/stock refresh and price history | NOT RUN |
| Catalog search proven to avoid synchronous retailer requests | NOT RUN |
| Rollback/readiness proof for live traffic | NOT COMPLETE |
| Shadow/canary traffic | BLOCKED — 0% |

## Required next steps

1. Await Bplatz's response. If it confirms an approved API/feed or grants written permission, record the exact scope and approval reference before any live request.
2. Monitor the NOTINO.fr application in CJ. Once approved, inspect the program terms and obtain the official feed access instructions; confirm permitted use before connecting it.
3. In parallel, evaluate alternative retailers that provide a documented API, product feed, or affiliate feed with terms permitting the intended use. Do not assume that an affiliate account alone authorizes scraping or feed reuse.
4. For the first retailer with a confirmed permitted method, configure it explicitly in isolated staging and run a narrowly bounded pilot. Keep the Bplatz task dormant unless Bplatz approval arrives.
5. Verify one genuine offer is persisted, validated, refreshed by Celery, represented in price history, and returned by catalog-first search without a synchronous retailer request.
6. Complete rollback, monitoring, and readiness checks before considering shadow traffic. Start with shadow only after Gate 0 approval; consider 5% canary only after shadow evidence is acceptable.

Do not create a synthetic published offer, scrape around a block, activate a retailer without a permitted access method, or enable shadow/canary traffic while the gate is blocked.

**Gate 0 remains BLOCKED; shadow/canary remain 0%.**
