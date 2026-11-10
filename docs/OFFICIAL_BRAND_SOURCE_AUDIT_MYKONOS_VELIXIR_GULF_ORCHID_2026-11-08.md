# Official brand source audit — Mykonos, Velixir and Gulf Orchid

**Audit date:** 2026-11-08  
**Scope:** source-level completeness and product-type classification only. This document does not add or remove catalog identities, variants, prices, stock, or offers.

## Executive findings

| Brand | Official source evidence | Existing catalog baseline | Audit conclusion |
|---|---|---:|---|
| Mykonos | Official brand storefront reports 54 products in its all-products collection. The official collection index separates fragrance families and product groupings. | 72 canonical identities (coverage-test lower bound) | Do not append products based on third-party lists. Reconcile the 72 existing identities against the current official 54-item listing, while retaining discontinued/historical identities only when independently documented. |
| Velixir | Brand's own perfume catalogue reports 28 of 28 perfumes, including 24 Eau de Parfum and four Extrait de Parfum. | 28 canonical identities | Current official listing count matches the existing baseline. Continue checking each detail page for exact sizes, concentration and source URL; count parity alone is not proof that every variant is complete. |
| Gulf Orchid | Official storefront exposes a dedicated Perfumes collection and separately classifies body mist, hair mist, deodorant, room spray, reed diffuser, mukhamaria and body lotion. | 23 canonical identities (coverage-test lower bound) | Prioritize a product-by-product pass over the dedicated perfume collection. Exclude body/home/personal-care product types from the fragrance identity catalog unless a separate supported product model is intentionally introduced. |

## Source observations

### Mykonos

- Official all-products collection: https://officialmykonos.com/collections/all
  - Current page reports **54 products**.
  - Product titles on the page explicitly expose concentration and some sizes, e.g. EDP 50 ml and Extrait de Parfum 50/100 ml.
- Official collections index: https://officialmykonos.com/collections
  - Lists 100 ml and 50 ml collections and scent-family collections.
- A separate EU catalogue at https://mykonosperfumes.eu/pages/explore reports 90 fragrances, but its own site describes the operator as an EU retailer. It is **not** treated as the brand's official source and none of its entries are eligible for automatic import on this basis.

**Required next check:** compare every existing Mykonos canonical identity with the 54 products in the official storefront; record "present", "not currently listed", or "needs historical evidence". Do not interpret "not currently listed" as proof that a fragrance never existed.

### Velixir

- Official perfume catalogue: https://velixirperfumes.eu/perfumes/
  - Reports 28/28 perfumes.
  - Distinguishes 24 Eau de Parfum and four Extrait de Parfum.
  - The page records sizes for listed products and summarizes recent additions; it explicitly notes that site appearance dates are not necessarily launch dates.

**Required next check:** verify each product detail page and variant against the canonical catalog. Do not derive a launch date from a page-publication date.

### Gulf Orchid

- Official perfume collection: https://shop-gulforchid.com/collections/perfume
- Official Gulf Orchid brand collection: https://shop-gulforchid.com/collections/gulf-orchid
- Official all-collections index: https://shop-gulforchid.com/collections

The storefront separates perfumes from:
- body mist, hair mist and deodorant;
- room spray and reed diffuser;
- mukhamaria and body lotion;
- bundles and gift sets.

A bundle or set must not become a canonical fragrance identity merely because it appears in a perfume-related collection. Individual fragrance names and explicit sizes should be captured from their own product pages.

## Catalog admission rules reaffirmed

1. An individual official product page or an official perfume-only listing must support each proposed identity.
2. Preserve the source URL and evidence URL.
3. Add a size or concentration only when explicitly stated by the source.
4. Keep spelling differences as aliases where they refer to the same product; do not create duplicate canonical identities.
5. Do not import prices, availability, retailer offers, shipping costs or stock from this catalog audit.
6. Distinguish perfumes from body-care, home-fragrance, deodorant, bundle and gift-set products.
7. A current storefront count is a snapshot, not proof of worldwide historical completeness.

## Status

This is a source-audit checkpoint, **not** a declaration that these three brand catalogs are complete. No catalog data was modified by this report.
