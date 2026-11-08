# Cross-PR catalog reconciliation audit

**Audit date:** 2026-11-08  
**Repository:** dalexmon81/ScentHunter  
**Scope:** compare open catalog PRs for overlapping canonical identities, variant tuples, source URLs and family-registry entries. This is a review checkpoint, not a merge or catalog mutation.

## Executive summary

The open PR set contains several independent branches that each pass their own catalog validation, but do not all validate the combined state. At least five cross-PR overlap groups require reconciliation before integration.

## Confirmed overlaps

### 1. Gulf Orchid — PR #542 vs PR #554

Two exact duplicate product records are present in both PRs:

| Canonical identity | Product ID | Official source | Variant |
|---|---|---|---|
| Cloud 9 | SH-GULF-ORCHID-CLOUD-9 | https://shop-gulforchid.com/products/cloud-9 | 100 ml EDP |
| Maestro | SH-GULF-ORCHID-MAESTRO | https://shop-gulforchid.com/products/maestro | 100 ml EDP |

The same product IDs and variant IDs are repeated, and the family registry contains repeated canonical entries. PR #554 is also currently reported by GitHub as not mergeable. Its head is six commits ahead and one behind its base branch, so it needs a base/conflict refresh as well as duplicate removal.

**Action:** keep one product row, one variant row and one family-registry entry per fragrance. Rebase/reconcile #554 against the branch containing #542 and retain only genuinely new products.

### 2. Velixir — PR #465 vs PR #517

Both PRs contain the same 24 product IDs and the same official Velixir product URLs. Both also introduce the same 48 product/size/concentration combinations: 35 ml EDP and 100 ml EDP for each of the 24 perfumes.

The variant IDs use different naming schemes:
- PR #465: `VAR-SH-VELIXIR-...`
- PR #517: `SHV-SH-VELIXIR-...`

Different IDs do not make these distinct variants. Combining the branches without reconciliation would create duplicate variant tuples for the same product and size.

**Action:** choose one canonical variant-ID scheme and add a regression test for unique `(product_id, size_ml, concentration)` tuples, not just unique `variant_id`.

### 3. Armaf — PR #564 vs PR #565

Both PRs add the same fragrance from the exact same official page:
- PR #564: `Check Mate White Knight`
- PR #565: `Check Mate White - Knight`
- Official page: https://cz.armaf.eu/en/products/check-mate-white-knight

This is a punctuation-only difference. Keep one canonical identity and the documented 100 ml EDP variant once; use aliases for legitimate spelling differences.

### 4. Armaf — PR #558 vs PR #565

Both PRs add `Odyssey French Kiss` as separate canonical product rows:
- PR #558 product ID: `SH-ARMAF-ODYSSEY-FRENCH-KISS`, source https://armaf.com/products/odyssey-french-kiss
- PR #565 product ID: `SH-ARMAF-1727c712`, source https://cz.armaf.eu/products/odyssey-french-kiss

The regional official page in #565 also documents a 60 ml EDP variant. Retain one canonical product, preserve both regional source URLs as evidence, and attach the 60 ml variant to that product.

### 5. Lattafa — PR #555 vs PR #562

The following identities appear in both expansions:
- Atlas Canyon
- Raghad
- Badee Al Oud Amethyst Fusion
- Farfasha
- Majd Al Sultan Black Intense
- Ramad / Ramaad Al Oud

Reconcile official spelling, canonical identity, aliases, product IDs, variants and source URLs. Do not create a second identity for a spelling variation.

## Overlapping Mykonos source-evidence work

PR #539 and PR #546 both upgrade the same existing Mykonos products from collection-level evidence to official product-detail-page evidence. Fourteen official detail-page URLs occur in both patches. This is overlapping source-evidence work, not by itself proof of duplicate product rows. Select one cumulative branch as the integration path and avoid replaying the same edits independently.

## CI status and limitation

The following individual catalog validation runs were checked and passed:
- PR #554 head: run 42517779599
- PR #517 head: run 42499610167
- PR #465 head: run 42470787169
- PR #546 head: run 42513510773

These green runs validate each branch separately. They do **not** prove the combined catalog is free of cross-PR duplicate product or variant records.

PR #565's current head still needs a fresh run on its exact SHA before it is considered validated. No merge has been performed as part of this audit.

## Required integration gate

Before any of these catalog PRs are integrated:

1. Reconcile the confirmed overlap groups above.
2. Validate the combined candidate branch, not only its component PRs.
3. Assert unique canonical identities by normalized brand + canonical name.
4. Assert unique product IDs.
5. Assert unique variant IDs.
6. Assert unique variant tuples by product ID + size + concentration.
7. Assert family-registry entries map one-to-one to canonical identities.
8. Preserve official evidence URLs and only record sizes/concentrations explicitly supported by those sources.

## Safety boundary

This audit changes documentation only. It does not change product catalog data, family registry, variants, prices, stock, offers, `main`, or production. No PR is merged or closed by this report.
