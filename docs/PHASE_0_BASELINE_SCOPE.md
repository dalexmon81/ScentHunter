# Phase 0 — Architecture preparation and operational acceptance

Phase 0 has two distinct acceptance layers. They must not be conflated.

## A. Architecture gate (required before Phases 1–11 continue)

The architecture gate is evaluated with repository evidence and disposable CI resources. It does **not** require live retailer authorization, real prices, populated production data or a live staging deployment.

- Keep the exact retailer scope documented: bplatz, deloox, easycosmetic, notino, orioudh, parfumcity, parfumzentrum, perfumemarket and sabina.
- Keep connector implementation, runtime registration and authorization status separate. Code presence is not permission.
- Keep Amazon DE and Amazon FR excluded from this scope.
- Preserve the baseline worker and offer-level CSV schema as the later operational evidence mechanism.
- Require a deterministic quality validator for the baseline CSV. Status-only rows do not count as offers; invalid prices, URLs, currencies, availability, matching state and duplicate offer keys fail validation.
- Require repeatable backup/restore coverage in disposable PostgreSQL CI and protected default-branch workflow.
- Keep all live retailer requests, persistent staging migrations, deployments, store activation and traffic changes behind explicit authorization.

The architecture gate can be accepted when the repository inventory, worker/CSV contract, validator, CI tests and safe disposable backup/restore path are implemented and pass. It does not certify real retailer coverage.

## B. Operational acceptance (performed after the integrated architecture, before user testing)

This is a separate release-readiness checklist. It must be completed only after Phases 0–11 are integrated on one release candidate and before operational user testing:

1. Obtain and record authorization/source access for each retailer that will actually be activated. Do not bypass HTTP 403/429, challenges or other access controls.
2. Generate the offer-level baseline from the approved operational source. Include all nine scope rows and explicit zero/failure statuses; only actual persisted offer rows count as offers.
3. Review per-store offer counts, valid price/currency/URL/availability, canonical match outcomes, duplicates and freshness.
4. Perform a backup and restore rehearsal against the actual persistent staging environment, recording the target, row counts and Alembic revision. A disposable CI database alone is not this rehearsal.
5. Confirm the staging API and frontend use the same populated PostgreSQL catalog.
6. Exercise metrics, alert delivery, quarantine recovery, human review, shadow comparison and rollback under approved conditions.

## Retailer scope and Notino policy

The nine-store scope is fixed for the baseline inventory. Notino.fr is restricted to the authorized CJ/VIV affiliate feed after publisher entitlement and feed access are confirmed. There is no HTML/product-page fallback for this project while that entitlement is pending. A connector being present or a public page being reachable does not grant permission. HTTP 401/403/429, challenges, timeouts, non-HTTPS or credential-bearing redirect destinations, or incomplete feed records are hard failures; never bypass controls, switch transport to evade a denial, or invent offers.

Notino's real-offer requirement belongs to the operational acceptance gate above. Its pending authorization must not block architecture work or fixture-based CI.

## CSV grain and quality

The operational baseline is one row per distinct retailer offer, retaining canonical product and variant matches where evidence supports them. It includes retailer, canonical product/variant IDs, fragrance identity, concentration, size, GTIN, retailer product ID, offer URL, price, currency, availability, capture time, source, match confidence/status and offer-validity flag.

The validator enforces the exact nine-store scope, non-empty real offers for every activated retailer, offer-level schema, HTTPS URLs, positive prices, currency syntax, explicit availability, matched/validated state and duplicate-key rejection. The operational baseline must include explicit zero rows for inactive or inaccessible retailers; those rows never count as offers.

## Safety boundary

This document does not authorize retailer requests, store activation, persistent database migrations, deployments, feature-flag changes, canary traffic or production operations. Use offline fixtures until the relevant access and environment approvals exist.
