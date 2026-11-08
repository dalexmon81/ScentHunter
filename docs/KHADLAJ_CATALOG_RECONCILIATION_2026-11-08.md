# Khadlaj catalog reconciliation — 2026-11-08

## Base and scope

This branch carries the Khadlaj reconciliation on top of `catalog/mykonos-reconciled-current-base-2026-11-08`. It preserves the Mykonos 99-identity / 102-variant catalog and all non-Khadlaj products from that base. It does not alter `main` or production.

## Final candidate counts

- 219 canonical Khadlaj identities.
- 218 explicit variants.
- 96 of 101 visible official Perfume Sprays names represented.
- 36 of 43 visible official Concentrated Perfume Oils names represented.
- All 42 products in the official La Fede EDP collection represented; three additional La Fede line products remain catalogued.
- Eight Shiyaaka identities retained as a distinct line.
- The 147-name Fragrantica designer listing is covered by canonical names or aliases; Fragrantica is not used to prove size or concentration.

## Reconciliation choices

- The broader Khadlaj identity/oil/La Fede harvest is retained, while overlapping official-variant work is used to improve individual product-page evidence.
- Thirty-eight overlapping variant records were upgraded from collection evidence to an exact official product page where one was available.
- Six additional retailer-supported variants were added for Ana Wa Anta, D'Love, Rasha, Safari Gold, Barwaaz Pure Navy and Vanilla Kiss. The retailer origin is documented in the audit; Vanilla Kiss concentration remains blank.
- The existing Riah-backed Opulence Bleu variant remains retailer-sourced.
- The generic “Private Blend” line label was removed as a canonical fragrance. Private Blend Tobac Extra and Private Blend Musk Ice remain separate products.
- Musk Pure Musk Blend Creation of Iqbal remains an alias of Musk Pure Musk Blend.
- Rasayel Vid is confirmed as 100 ml EDP by the official product page heading despite the stale “extrait” token in its URL.
- Shiyaaka Rose Gold is confirmed as 100 ml EDP by its individual official Kuwait page.
- Alf Wardaat is 30 ml Perfume Oil; the official product page title confirms 30 ml despite the legacy URL slug.
- Perfume oils remain distinct from alcohol-based spray products.

## Data integrity

- No duplicate product IDs or variant IDs.
- No orphan variants.
- No duplicate product-size-concentration combinations.
- Every variant has a source evidence URL.
- Product sizes agree with their parent product's `formats_ml`.
- The family registry is synchronized across the five Khadlaj families.

## Known gaps

The official store snapshot still exposes five spray collection entries and seven concentrated-oil entries that were not individually reconciled in the inspected pages. They remain out of the canonical seed until names and product types can be verified. This is not a claim of worldwide historical completeness or current stock.

See [KHADLAJ_CATALOG_AUDIT_2026-11-08.md](KHADLAJ_CATALOG_AUDIT_2026-11-08.md) for the detailed source and variant audit.
