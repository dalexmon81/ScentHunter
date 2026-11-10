# Cumulative official catalog integration audit — 10 November 2026

## Integration lineage

This branch consolidates the two parallel catalog lines that both descended from the Khadlaj consolidation branch:

- PR #654 / #658: cumulative official-source integration, including Gulf Orchid new arrivals, Maison Asrar audits, Velixir, Arabiyat Prestige and the Armaf Intenso Fuego detail audit.
- PRs #655 → #656 → #657: four additional Gulf Orchid launch variants, Maison Asrar brand-attribution corrections, and refreshed Velixir / Arabiyat Prestige evidence.

The integration is based on the #658 head and is intended to target the #649 Khadlaj cumulative base. It does not target or modify main.

## Reconciliation decisions

- Preserve the #654 line's Maison Asrar detail-page provenance and the Armaf Club de Nuit Intenso Fuego 105 ml variant.
- Preserve the four existing Gulf Orchid new-arrival identities and variants from the earlier cumulative line.
- Remove the two duplicate Gulf Orchid identities for Vanilla Aura and Vanilla Voyage. Keep the existing Maison Asrar canonical product IDs and attach the official Maison Asrar attribution evidence.
- Add only five additional variants with explicit product-page specifications: Al Qasr 100 ml EDP, Exotic Oud 100 ml EDP, Vanilla Latte 100 ml EDP, Cookie Bite 100 ml EDP, and Maison Asrar Vanilla Aura 100 ml EDP.
- Keep Tahara Vanilla Musk as a verified product name only. Its current product page does not expose size or concentration in the visible specification; the URL slug alone is not used to create a variant.
- Keep Maison Asrar Vanilla Voyage as a verified name only. The current official page does not expose size or concentration.
- Keep Arabiyat Prestige Marwa as a name-only canonical record. The previously cited individual URL is not currently accessible, while the official collection exposes “Arabiyat Marwa Extrait 60 ml”, which does not support the claimed 100 ml EDP variant.
- Refresh Velixir official storefront evidence while preserving all existing variant IDs and aliases.
- Do not import prices, stock, availability, shipping, or retailer offers.

## Structural validation before CI

The merged JSON snapshot was independently checked before writing:

- 2,208 canonical products.
- 974 variants.
- Zero duplicate product IDs.
- Zero duplicate variant IDs.
- Zero duplicate normalized brand/name identities.
- Zero duplicate product/size/concentration tuples.
- Zero duplicate GTINs.
- Zero orphan variants.
- Zero variants missing their parent product's declared format.
- Zero canonical variants containing retail offer fields.

These figures describe this integration branch's written snapshot. The exact-head GitHub Actions run remains the final validation gate.
