# Khadlaj catalog audit — 2026-11-08

## Snapshot

This draft contains **219 canonical Khadlaj fragrance identities and 218 explicit variants**. It is stacked on the current Mykonos reconciliation branch and preserves the other catalog records already on that base.

The catalog separates the main spray range, concentrated perfume oils, Shiyaaka and La Fede. Fragrantica is used only as a name-discovery cross-check, never as evidence for size or concentration.

## Official range reconciliation

| Official Khadlaj collection | Collection count | Visible names reconciled | Remaining |
|---|---:|---:|---:|
| Perfume Sprays | 101 | 96 | 5 not exposed in the inspected collection pages |
| Concentrated Perfume Oils | 43 | 36 | 7 not exposed in the inspected collection pages |
| La Fede Eau de Parfum | 42 | 42 | 0 |

The counts are a snapshot of the official store, not a stock claim. The remaining five spray and seven oil entries are not guessed into the catalog. The separate Shiyaaka line contains eight identities.

## Catalog and variant quality

- 219 unique canonical product IDs.
- 218 unique variant IDs.
- No orphan variants.
- No duplicate product-size-concentration combinations.
- All 218 variants have a `source_evidence_url`.
- 127 variant records point to product-detail pages; 86 point to official collection pages whose product cards state the variant data.
- 150 Eau de Parfum, 25 Extrait de Parfum, 41 Perfume Oil and 2 variants with concentration deliberately unspecified.
- Six additional variants are supported by specialist retailers; together with the existing Riah listing, seven retailer-backed variants are clearly distinguishable from first-party Khadlaj evidence.

Retailer-backed variants:
- Ana Wa Anta — Notino Belgium, 20 ml Perfume Oil.
- D'Love — Notino France, 15 ml Perfume Oil.
- Rasha — Primor, 12 ml Perfume Oil.
- Safari Gold — Notino Italy, 20 ml Perfume Oil.
- Barwaaz Pure Navy — Triple Traders, 100 ml EDP.
- Vanilla Kiss — Arabic Oasis, 50 ml; concentration left unspecified.
- Opulence Bleu — Riah, 100 ml EDP.

These retailer records remain `source_listed_name` where appropriate; they are not represented as first-party confirmations.

## Identity decisions

- **Private Blend** is a line label, not a distinct fragrance SKU in the reviewed source pages, so it is not a canonical product. The actual products **Private Blend Tobac Extra** and **Private Blend Musk Ice** remain separate.
- **Musk Pure Musk Blend Creation of Iqbal** is an alias of **Musk Pure Musk Blend**, not a duplicate canonical product.
- **Rasayel Vid** is 100 ml EDP. The URL slug contains the word “extrait”, but the official product page heading and product content say Eau de Parfum.
- **Shiyaaka Rose Gold** is 100 ml EDP, supported by its individual Khadlaj Kuwait product page.
- **Alf Wardaat** is 30 ml Perfume Oil. Its URL slug contains “25ml”, but the official page heading and product collection identify it as 30 ml.
- **Hareem Al Sultan Gold** remains a 35 ml Perfume Oil, not a spray variant.
- **Pure Musk** retains separate 20 ml Perfume Oil and 100 ml EDP variants under one product identity.
- **Saqr Al Badiya** concentration remains unspecified because the official page's title and description conflict.
- **Vanilla Kiss** size is retailer-listed at 50 ml; concentration remains unspecified.

## Family registry

The registry carries five Khadlaj families: main catalog, official spray harvest, Shiyaaka, La Fede and concentrated perfume oils. Family memberships overlap intentionally for line navigation; they are not additive canonical product counts.

## Sources

- Official perfume sprays: https://khadlaj-perfumes.com/collections/perfumes-spray
- Official concentrated perfume oils: https://khadlaj-perfumes.com/collections/concentrated-perfume-oils
- Official La Fede EDP: https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume
- Official Shiyaaka Rose Gold page: https://kw.khadlaj-perfumes.com/products/shiyaaka-for-women-spray-shop-online-best-price-in-dubai-uae
- Official Rasayel Vid page: https://khadlaj-perfumes.com/collections/khadlaj-new-launches/products/rasayel-vid-100-ml-extrait-de-parfum-spray-copy
- Official Alf Wardaat page: https://khadlaj-perfumes.com/products/alf-wardaat-25ml
- Fragrantica designer index (name cross-check only): https://www.fragrantica.com/designers/Khadlaj.html

## Validation

Focused regression tests cover catalog/family parity, La Fede detail pages, the official spray harvest, variant provenance, oil/spray separation and the reconciled 219/218 totals. GitHub Actions status is pending for this draft.
