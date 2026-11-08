# Velixir official product-page and size reconciliation — 8 November 2026

## Scope and source

This evidence set reconciles all 28 Velixir fragrance identities already present in the cumulative catalog against individual product pages on the brand-owned Velixir Parfums store. The 48 variants were already present in cumulative PR #527; this integration carries their dedicated regression test and source documentation without duplicating the rows.

Official catalog:
https://velixirparfums.com/collections/all

The current official collection contains 29 listings, including a Discovery Set. That set is a multi-sample bundle and is not imported as a canonical fragrance identity. The 28 existing perfume identities are all represented by individual official product pages.

## EDP sizes and variants

The 24 Eau de Parfum product pages explicitly offer two sizes: 35 ml and 100 ml. The catalog now has both variants for each of these identities:

Adonis, Aphrodite, Apollo, Ares, Artemis, Asteria, Athena, Concordia, Demeter, Galatea, Harmonia, Helios, Hera, Himeros, Icarus, Morpheus, Narcisus, Nyx, Orion, Paladin, Persephone, Poseidon, Selene, Uranus.

This adds 48 variants and sets `formats_ml: [35, 100]` on the corresponding product and family-registry records.

## Extrait products

The official individual pages confirm the concentration for four additional identities:
- Comus
- Ether
- Orpheus
- Panacea

Those pages do not expose a bottle-size selector or state a bottle size in the retrieved product detail. Their individual official URLs are attached, but no size or variant is invented. Their product-level concentration remains Extrait de Parfum.

## Source reconciliation

For all 28 products:
- `source_url` and `source_evidence_url` now point to the individual brand-owned product page.
- The existing canonical identity and product ID are preserved.
- No new canonical products are added.
- No price, stock, availability, shipping, or offer data is copied into the canonical catalog.

## Snapshot after change

- Integrated cumulative snapshot: 2,743 canonical identities
- Integrated cumulative snapshot: 717 variants
- Velixir identities: 28
- Velixir variants: 48
- EDP identities with explicit sizes: 24
- Extrait identities with no size evidence: 4

## Regression protection

`backend/tests/test_velixir_official_product_variants.py` checks all 28 official page URLs, both EDP sizes, registry alignment, the deliberate omission of sizes for the four Extrait pages, unique variant IDs, and valid parent references.
