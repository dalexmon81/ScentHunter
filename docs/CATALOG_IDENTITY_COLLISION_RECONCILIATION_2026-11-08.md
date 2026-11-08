# Catalog identity collision and product-form audit — 8 November 2026

## Scope

This is a conservative reconciliation of the catalog snapshot inherited from PR #534. It focuses on normalized product-name collisions, shared aliases, and evidence that could cause unlike product forms to be compared as equivalent.

The audit is not a claim that the whole catalog is complete. It does not change retailer offers, prices, stock, scraping, APIs, or deployed services.

## French Avenue: two duplicate listing identities consolidated

The read-only identity audit found no duplicate normalized brand/name pairs in the original 2,061-product snapshot, but it did find two shared product aliases:

| Existing catalog rows | Shared alias | Official product-page evidence | Action |
|---|---|---|---|
| Genesis Aries / Aries | Aries | https://frenchavenue.com/products/aries | Keep one canonical identity, named Aries, in the Genesis family |
| Genesis Aquarius / Aquarius | Aquarius | https://frenchavenue.com/products/aquarius | Keep one canonical identity, named Aquarius, in the Genesis family |

The official Genesis collection lists Aries and Aquarius among its 12 products:
https://frenchavenue.com/collections/genesis

The individual pages identify the purchasable products as **Aries** and **Aquarius**, and specify **EDP, 100 ml**. The product pages and collection context therefore support one identity for each scent, rather than separate Genesis-prefixed and unprefixed products.

Reconciliation details:
- Preserved the existing Genesis-family product IDs.
- Changed their canonical names to the storefront product names, Aries and Aquarius.
- Retained both Genesis-prefixed names as aliases.
- Moved the individual product page into `source_url` and `source_product_url`; kept the Genesis collection as `source_evidence_url`.
- Promoted the two identities to `source_verified_name`.
- Added one 100 ml Eau de Parfum variant to each identity.
- Did not add GTINs: the inspected product pages do not provide a barcode in the captured evidence.
- Removed the two extra general-catalog rows only after confirming that they had no variants referencing them.

The Genesis family remains 11 identities. French Avenue's catalog row count changes from 119 to 117 because two duplicate records are removed; this is not a loss of distinct product-page identities.

## Product-form safeguard: Maison Alhambra Amber & Leather

The official Maison Alhambra USA page found for Amber & Leather is explicitly a **perfumed deodorant spray**, 250 ml, barcode **6291108731925**:
https://maisonalhambra-usa.com/products/maison-alhambra-amber-and-leather-perfumed-deodorant-spray-for-men

That page is not evidence for an Eau de Parfum variant. The existing catalog identity remains listing-level and receives no deodorant GTIN, size, concentration, or variant. A separate perfume-specific product page is required before enriching the perfume identity.

This is a negative evidence result, not a claim that a perfume with the same name does not exist.

## Product-form data-model gap

The current seed has no explicit `product_form` field. Names and concentration alone are not a reliable way to distinguish:
- alcohol-based perfume sprays (EDP, EDT, extrait);
- perfume oils / attars;
- deodorant sprays and deodorant sticks;
- body mists, hair mists and body sprays;
- body lotions and shower gels;
- home fragrances, room sprays and diffusers;
- gift sets and discovery sets.

Do not infer that two records are the same product merely because the brand and fragrance name match. Do not inherit a barcode, size, concentration or price across different forms. Concentration (EDP/EDT/extrait) is not a substitute for product form.

A future schema change should introduce an explicit, validated product-form classification and represent gift sets / bundles separately from single fragrances. This PR deliberately does not add an unconsumed field or alter matching behavior.

## Structural checks performed on the updated JSON

- 2,059 canonical product identities.
- 296 variants.
- No duplicate product IDs.
- No duplicate variant IDs.
- No orphan variants or variant sizes absent from the parent product's `formats_ml`.
- No duplicate normalized brand/name pairs.
- No remaining shared product aliases in the catalog snapshot.
- The two reconciled Genesis identities each have one 100 ml EDP variant.
- Amber & Leather remains without the deodorant barcode and without a perfume variant.

These are structural checks of the JSON snapshot. Automated GitHub Actions results are reported separately; they must not be inferred from this document.

## Files changed

- `backend/product_catalog.json`
- `backend/family_registry.json`
- `backend/tests/test_requested_brand_catalog_coverage.py`
- `backend/tests/test_catalog_family_registry_coverage.py`
- `docs/CATALOG_IDENTITY_COLLISION_RECONCILIATION_2026-11-08.md`
