# Notino pilot — Dior Sauvage EDP 100 ml

**Selected pilot:** Notino.fr, using the existing authorized CJ/VIV XML affiliate-feed connector in the Phase 5 branch.

**Execution status: NOT RUN.** This runbook is an approved technical direction, not proof that feed credentials are available or that an offer exists. No live feed request, cloud resource, migration, deployment, or production write is performed by preparing this document.

## Why Notino

The Phase 5 connector NotinoAffiliateFeedConnector:
- consumes the CJ/VIV XML feed through the existing affiliate_feed parser;
- accepts an injected byte loader for isolated tests;
- returns normalized OfferRecord evidence and retains the exact XML bytes as a raw artifact;
- does not write to either legacy SQLite or canonical PostgreSQL;
- uses the feed again for price/stock refresh rather than scraping a product page.

The underlying feed fetch requires these environment variables, configured only as protected staging secrets:
- NOTINO_CJ_FEED_URL
- NOTINO_CJ_FEED_USERNAME
- NOTINO_CJ_FEED_PASSWORD

Never print, log, commit, paste into a PR, or include these values in diagnostic output. A missing or denied credential must fail closed.

## Preconditions — all required

1. Confirm that the CJ/VIV publisher account has an active Notino.fr product feed entitlement and that the feed is authorized for this use.
2. Configure the three variables above in the dedicated staging worker app only. Do not copy production secrets or use a production feed URL unless the account owner has explicitly approved it for staging.
3. Confirm separate staging PostgreSQL and Redis endpoints. Do not use production connection strings.
4. Provision a staging stores row for slug=notino, name=Notino, domain=notino.fr, country=FR, currency=EUR, status=active. The existing canonical seed script deliberately provisions Bplatz only; do not change it to silently activate Notino.
5. Verify the seeded canonical fragrance and exact ProductVariant for Dior Sauvage / Eau de Parfum / 100 ml. Record the UUIDs from staging read-only queries. If the exact variant is absent, stop: do not infer or create a variant as part of offer ingestion.
6. Approve the cost of a persistent Fly staging worker before deploying it. If not approved, run only in disposable GitHub Actions infrastructure.

## Controlled pilot procedure

### A. Credential and feed preflight

- Verify secret presence without echoing values.
- Run one bounded feed fetch from the staging environment with the connector's existing HTTPS, redirect, timeout, response-size, XML-safety and XML-parse protections.
- Record only a redacted status, capture time, byte count, SHA-256, feed entry count and safe error code.
- Confirm that the XML contains an entry for the exact product and that its product URL is on www.notino.fr.
- Do not save the XML to a public CI artifact. Store raw feed bytes only in the protected staging ingestion_artifacts store, where access is restricted.

### B. Product identity gate

The feed item must independently confirm:
- brand resolves to the canonical Dior brand;
- fragrance resolves to Sauvage (not Eau Sauvage or another Dior line);
- concentration is Eau de Parfum;
- size is exactly 100 ml;
- product URL is the matching Notino.fr item;
- GTIN, if present, passes checksum validation and agrees with the exact canonical identity.

The matcher in Phase 5 is intentionally conservative: verified GTIN plus identity agreement, or an exact canonical key. No fuzzy auto-match is permitted. Any conflict, absent exact variant, ambiguous identity, wrong concentration, wrong size or wrong Dior line remains unmatched and is sent for review. It must not be promoted.

### C. Offer quality gate

Required source fields:
- stable external product/offer ID;
- HTTPS Notino.fr product URL;
- positive EUR price;
- explicit in_stock or out_of_stock availability;
- feed capture timestamp.

Important implementation detail: the feed parser can represent unknown and preorder, and the generic connector validator accepts those values, but the canonical promotion service currently permits only in_stock and out_of_stock. Therefore unknown/preorder rows must remain unpublished; do not weaken the canonical promotion gate to make the pilot pass.

### D. PostgreSQL + Celery vertical slice

Using only the isolated staging environment:
1. Run one discovery task for notino.
2. Verify one ingestion_runs row and an immutable XML ingestion_artifacts row with SHA-256.
3. Verify the raw offer is staged in ingestion_raw.
4. Verify normalized identity and exact product_variant_id match.
5. Verify the raw row reaches promoted only after all gates pass.
6. Read the active offers row in a new database session. Assert store slug, external product ID, URL, EUR price, availability, and exact Dior Sauvage EDP 100 ml variant UUID.
7. Verify matching price_history and match_audit records.
8. Enqueue one refresh through Redis/Celery. Verify the connector reloads the affiliate feed, stages the new observation, and updates the same offer identity without creating a duplicate offer.
9. Verify a normal product search reads the stored offer and makes no synchronous retailer request.

If the feed does not contain the exact SKU, the run is a valid no-match/no-publication result. Do not substitute another size, concentration, retailer or product.

## Evidence to attach to PR #345

- staging environment identifier (not secret values);
- redacted feed preflight status, timestamp, byte count and SHA-256;
- exact canonical fragrance and variant UUIDs;
- ingestion run ID, raw row ID, artifact ID and offer UUID;
- matcher method/confidence and validation outcome;
- Celery task IDs and worker log excerpts with no credentials or full feed body;
- before/after counts for offers, price history, match audit and duplicate checks;
- read-only search proof and HTTP request trace showing no live retailer fetch during user search;
- CI run links and health endpoint result.

## Stop conditions

Stop immediately if:
- staging secrets are missing, denied, or resolve to an unapproved account/feed;
- the feed returns HTML, an unsafe or malformed XML document, or an off-domain product URL;
- exact product identity or variant mapping cannot be proven;
- price/currency/availability is missing or invalid;
- any write targets production;
- the worker or staging database/Redis configuration is not isolated;
- a persistent worker cost has not been approved.

## Rollout boundary

A successful one-product pilot proves only the Notino connector path for this exact SKU in staging. It does not close the wider Phase 5 gate, approve other stores, or authorize 5% user traffic. Phase 11 remains at 0% until the wider Gate 0 criteria and rollback checks pass.
