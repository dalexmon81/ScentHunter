# Cumulative Al Wataniah and Paris Corner reconciliation — 10 November 2026

## Base and reconciliation method

This draft starts from the exact validated PR #663 head, commit `d6d08c2cac5a9058eb17924a9e2c6225471fd569`. It carries forward only the Al Wataniah and Paris Corner deltas from the separate #666 and #667 branches. Those source branches had diverged from the latest #663 head; three-way comparisons against their common bases found no conflicting changes in the affected canonical products, variants, or family-registry rows. Unrelated stale-branch changes were not copied.

Existing canonical product IDs and variant IDs are preserved. Product records, explicit variants, and family registry rows are reconciled together.

## Al Wataniah

- Retains all 86 existing canonical product identities.
- Records 81 individual official product pages that explicitly state 100 ml Eau de Parfum.
- Adds 79 new variant records and enriches two existing variants in place.
- Keeps House Of Oud and Anwan as identity-only because accessible official pages do not explicitly state size and concentration.
- Keeps Rawaee Noble, Rawaee Regina and Redaa listing-only.
- Synchronizes the family registry and preserves the Da'im alias.

## Paris Corner Europe

- Retains all eleven existing canonical product identities.
- Adds six missing variants and enriches five existing variants in place.
- Records ten 100 ml Eau de Parfum variants and Ibisco Nirvana at 65 ml Eau de Parfum.
- Preserves the original discovery/evidence URLs and records the Europe storefront product-detail URLs separately.

## Exact assembled snapshot — structural checks before CI

- 2,208 canonical products.
- 1,069 variants.
- 81 Al Wataniah variants.
- 22 brands and 34 family-registry records.
- Zero duplicate product IDs, variant IDs, normalized brand/name identities, product/size/concentration tuples or GTINs.
- Zero orphan variants or undeclared variant sizes.
- Zero canonical variant records containing price, currency, stock, availability, shipping, retailer or offer fields.
- 237 source-verified products remain without explicit variants; unsupported sizes and concentrations remain unset.

These structural checks were run against the exact assembled JSON in this branch. GitHub Actions on the exact PR head remains the final validation gate.
