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
- Preserve the four official Khadlaj variants added and merged through PR #661: Panache Eleganza, Oud Noir, Ombre Notes and Infini. Keep the original canonical product and variant IDs, official URLs, sizes, concentrations and supported GTINs.
- Refresh Velixir official storefront evidence while preserving all existing variant IDs and aliases.
- Do not import prices, stock, availability, shipping, or retailer offers.

## Structural validation before CI

The merged JSON snapshot was independently checked before writing:

- 2,208 canonical products.
- 985 variants.
- Zero duplicate product IDs.
- Zero duplicate variant IDs.
- Zero duplicate normalized brand/name identities.
- Zero duplicate product/size/concentration tuples.
- Zero duplicate GTINs.
- Zero orphan variants.
- Zero variants missing their parent product's declared format.
- Zero canonical variants containing retail offer fields.

These figures describe this integration branch's written snapshot. The exact-head GitHub Actions run remains the final validation gate.


## Khadlaj follow-up reconciliation

PR #661 was merged into the cumulative Khadlaj base after the earlier integration snapshot. Its four official variants are retained in this corrected snapshot with their original canonical IDs and the source evidence recorded in the catalog. The two unsupported offers described above (Tahara Vanilla Musk and Arabiyat Prestige Marwa) remain excluded; no speculative replacement variants were created.

## Paris Corner official E-shop detail reconciliation — 10 November 2026

Four existing Paris Corner canonical identities now have product-level evidence from the brand's official European e-shop, which identifies itself as the official Paris Corner e-shop and publishes explicit type and size attributes:

| Existing canonical identity | Official E-shop attributes | Evidence |
|---|---|---|
| Bayn Al Asrar | 80 ml Eau de Parfum | https://de.pariscornereurope.com/en/products/paris-corner-bayn-al-asrar-edp-w-80-ml |
| December Vanilla | 85 ml Eau de Parfum | https://de.pariscornereurope.com/en/products/paris-corner-december-vanilla-edp-u-85-ml |
| Coconut Lagoon | 100 ml Eau de Parfum | https://de.pariscornereurope.com/en/products/coconut-lagoon |
| Cherry Cola (listed as Cherry Cola Emir on the European shop) | 75 ml Eau de Parfum | https://de.pariscornereurope.com/en/products/cherry-cola-emir |

All four records reuse existing canonical product IDs; the family registry now declares the same sizes. The official pages do not expose GTIN/barcodes, so none are added. The shop's product page metadata and descriptions are treated as identity/variant evidence only; no price, stock or offer data is imported.
Three further products were completed using official Paris Corner Europe detail pages:

| Existing canonical identity | Official E-shop attributes | Evidence |
|---|---|---|
| Eternal Coffee | 85 ml Eau de Parfum | https://de.pariscornereurope.com/en/products/eternal-coffee |
| Eternal Meadows | 85 ml Eau de Parfum | https://de.pariscornereurope.com/en/products/eternal-meadows |
| Eternal Musk | 85 ml Eau de Parfum | https://de.pariscornereurope.com/en/products/eternal-musk |

These are existing canonical product IDs; no new product identities or GTINs were created. The registry formats match the catalog variants.