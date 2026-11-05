# Phase 11 — Bplatz pilot runbook

**Selected pilot:** Bplatz — French Avenue Liquid Brun Eau de Parfum 100 ml.  
**Execution status:** NOT RUN on the Phase 5 PostgreSQL/Celery stack.  
**Traffic status:** 0% new API; shadow/canary remains blocked.

This runbook replaces Notino as the selected candidate for the first controlled staging pilot. Notino is deferred.

## Product identity already present in the repository

The committed Bplatz fixture is a captured product-page response dated 2026-11-02:

- Requested URL: `https://bplatz.de/products/fragrance-world-liquid-brun-eau-de-parfum-100ml?variant=54015243419916`
- Captured Shopify variant ID: `54015243419916`
- Captured SKU and GTIN: `6290360375694`
- Canonical legacy product: `SH-0030`
- Canonical legacy variant: `VAR-f87146c82d167f4c`
- Fixture SHA-256: `9f76b00bc7472ccd389116302f06e2e02f258dc17fee7f43371993f79284c017`

The captured response is historical evidence only. Its price and stock must not be treated as current. The live page must be fetched again only after source-access approval, and all offer fields must be parsed from that response.

## Current evidence

- Bplatz connector is registered as runtime key `bplatz`.
- Adapter wraps the existing Bplatz scraper and emits normalized offer records; it does not write to the canonical database itself.
- Existing legacy persistence proof covers this Liquid Brun fixture on the older persistence path only.
- Phase 5 CI has tested the Bplatz fixture path synthetically, including matching, promotion, price history and refresh behavior. This does not establish a live Phase 5 offer.
- PR #347 adds an offline B1 matrix for stock states, invalid prices, currencies, sizes/concentrations and missing identifiers. Push workflow run `41967161582` passed.
- **New Bplatz-specific artifact-linkage test passed:** PR #343 commit `99c2842287df681d8cd5c5abece4aeef97c9068f`, workflow run [`41967935150`](https://github.com/dalexmon81/ScentHunter/actions/runs/41967935150). The test loads the committed Liquid Brun fixture offline, runs the Bplatz parser/connector through Celery discovery, and verifies original HTML bytes, SHA-256, artifact-to-ingestion-run linkage and the raw-evidence artifact reference. Both `ingestion-pipeline` and `runtime-integration` jobs passed.
- This is fixture-only CI evidence in disposable test infrastructure. It does not establish live source access, a current offer, persistent staging or a real retailer refresh.
- No live Bplatz request, Phase 5 staging write, Celery refresh of a real offer, or search/no-retailer-call proof has been performed.

## Gate B1 — fixture and source review

### Fixture tests

The B1 matrix must remain offline and cover:

- explicit in-stock, out-of-stock, preorder and unknown availability;
- missing, empty, zero, negative and malformed prices;
- EUR and foreign-currency rejection (never relabel a foreign amount as EUR);
- 100 ml and conflicting sizes;
- Eau de Parfum, Eau de Toilette and Extrait concentration parsing;
- absent SKU/GTIN remain absent.

Bplatz-specific work still required before a live run:

- verify retry/quarantine isolation for blocked, timeout and unavailable responses;
- verify the complete wrong-size and ambiguous-match rejection path using the Phase 5 matcher and promotion service.

Artifact persistence/linkage is covered by the offline Bplatz-specific test cited above; it is not a live ingestion proof.

### Source-access review — mandatory stop gate

Before any live request, the repository owner must confirm:

1. Bplatz current terms and policies permit the intended automated access method.
2. The selected access method does not bypass authentication, anti-bot controls, rate limits or other restrictions.
3. The request scope and rate are bounded to this one product.
4. The captured product URL remains valid and is on the expected Bplatz domain.

If permission or the allowed method cannot be confirmed, stop. Do not attempt alternate domains, proxies, browser automation, or scraping to work around a block.

### Public terms review — 2026-11-05

The public Bplatz terms page was reviewed: https://en.bplatz.de/pages/purchase-clauses. It describes consumer purchase contracts, payment, delivery, returns and applicable law. It does **not** expressly grant permission for automated product-page collection or define an allowed automated-access method. The public terms therefore do not establish scraping authorization.

The site's `/robots.txt` could not be retrieved in this review. Its contents and any crawl directives remain unverified. This is not evidence that access is allowed or denied.

**Decision: source-access gate remains NOT VERIFIED.** Do not run a product-page request, feed fetch, browser automation or scraper until the repository owner confirms an authorized method (for example, written permission or an approved affiliate/feed arrangement). If that cannot be confirmed, choose a permitted data source instead.

## Gate B2 — one-offer Phase 5 staging proof

Only after B1 and source-access approval:

1. Confirm isolated staging PostgreSQL and Redis; production connection strings are forbidden.
2. Confirm the canonical Liquid Brun product and 100 ml EDP variant mapping in persistent staging. Do not trust fixture IDs as database UUIDs.
3. Provision Bplatz explicitly in the staging stores table; do not activate it through a general seed.
4. Perform one bounded product-page fetch through the registered Bplatz connector using the approved access method.
5. Persist the source bytes in `ingestion_artifacts`, with SHA-256, byte length and ingestion-run linkage.
6. Stage the raw offer and verify brand, fragrance, EDP concentration, 100 ml size, source URL and identifiers.
7. Match only to the exact canonical variant. Any identity conflict or ambiguity stays unmatched.
8. Promote only with a positive EUR price, explicit `in_stock` or `out_of_stock` status, valid URL, timestamp and active store.
9. Read the offer back in a new PostgreSQL session; verify store, external identity, URL, price, currency, stock and exact variant.
10. Enqueue one Celery refresh and verify it updates the same offer identity, writes price history and creates no duplicate.
11. Run a normal catalog search and prove it reads stored/indexed data with zero synchronous Bplatz requests.
12. Attach sanitized run IDs, task IDs, artifact hash, offer UUID, variant UUID and read-only search trace to PR #345.

A missing or ambiguous product, unavailable page, unknown stock, invalid price or blocked request is a valid stop outcome. Never substitute another product or invent an offer.

## Infrastructure and cost boundary

- Use a disposable GitHub Actions environment if it can exercise the complete isolated staging path.
- Do not deploy a persistent Fly worker until its cost is reviewed and explicitly approved.
- Do not reuse production secrets, database URLs, Redis URLs or volumes.
- Never paste credentials into chat, commits, PRs or logs.

## Gate B3 — shadow-read eligibility

A successful B2 pilot proves only this Bplatz product path. It does not automatically authorize shadow traffic or the 5% canary. Wider Gate 0 checks, monitoring, kill switch, rollback and explicit rollout approval remain mandatory.

## Current decision

| Item | Status |
|---|---|
| Bplatz connector registered | PASS |
| Historical Liquid Brun fixture | PASS |
| Legacy persistence proof | PASS, legacy path only |
| Offline B1 matrix | PASS in PR #347 CI |
| Bplatz fixture artifact/run linkage | PASS, offline CI only — PR #343 run 41967935150 |
| Retry/quarantine and wrong-size/ambiguous-match cases | OPEN |
| Current source terms and permitted access | NOT VERIFIED |
| Persistent Phase 5 staging resources | NOT VERIFIED |
| Real offer in Phase 5 PostgreSQL | NOT RUN |
| Celery refresh of real Bplatz offer | NOT RUN |
| Search without synchronous retailer request | NOT RUN |
| Phase 11 shadow/canary | BLOCKED |
