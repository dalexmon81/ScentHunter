# Cumulative official catalog integration — 10 November 2026

## Integration base

This draft continues the verified catalog line from PR #657 and retains its Gulf Orchid, Maison Asrar attribution, Velixir, and Arabiyat Prestige work. It also carries forward compatible detail-page improvements from the parallel PR #654 line.

## Reconciled records

- Retains the Maison Asrar attribution for Vanilla Aura and Vanilla Voyage and removes the duplicate Gulf Orchid identities.
- Retains the five explicitly sized Gulf Orchid variants: Al Qasr (100 ml), Tahara Vanilla Musk (60 ml), Exotic Oud (100 ml), Vanilla Latte (100 ml), and Cookie Bite (100 ml), all Eau de Parfum.
- Retains the four Velixir Sacred Four fragrances with 35 ml and 100 ml Extrait de Parfum variants.
- Retains the four Arabiyat Prestige launch variants: Aariz (100 ml), Aariz L’Absolu (100 ml), Asháa Oud Noir (110 ml), and Marwa (100 ml), all Eau de Parfum.
- Carries forward official detail-page provenance for Maison Asrar Rosé Absolute and Rosé Bouquet without inferring bottle sizes or concentrations.
- Carries forward Armaf Club de Nuit Intenso Fuego's official 105 ml Eau de Parfum variant.
- Preserves existing canonical product IDs.

## Structural checks on the assembled JSON

- 2,208 canonical products.
- 976 explicit variants.
- Zero duplicate product IDs.
- Zero duplicate variant IDs.
- Zero duplicate normalized brand/name identities.
- Zero duplicate product/size/concentration tuples.
- Zero duplicate GTINs.
- Zero orphan variants.

No prices, stock, availability, shipping, or retailer-offer data is imported. This is a draft integration branch; no merge to main or production is performed. GitHub Actions on this exact head is the final validation gate.

## First CI feedback incorporated

The first exact-head workflow run identified two missing Maison Asrar product-page URL fields (Belgravia and Regent) and one legitimate increase in the verified-name/no-variant queue because Vanilla Voyage is verified without a documented bottle size. The catalog provenance fields and the quality-debt ceiling were corrected; the updated head requires a fresh workflow run.
