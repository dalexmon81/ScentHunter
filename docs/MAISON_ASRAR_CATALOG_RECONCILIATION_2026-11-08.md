# Maison Asrar catalogue reconciliation — 2026-11-08

## Scope and source hierarchy

This audit compares the ScentHunter Maison Asrar seed against:
- Maison Asrar's official store: https://maisonasrar.com/collections/all
- Official fragrance-only collection: https://maisonasrar.com/collections/perfume-sprays
- An independent EU retailer's reference guide: https://maisonasrarperfumes.eu/fr/perfumes/
- Individual Maison Asrar product pages on Gulf Orchid's retailer site for three additional products.

The EU guide explicitly says it is unofficial and independently operated by FragranceGems. It lists 116 Maison Asrar perfume names and says its notes/families are based on the brand's own product pages, checked 24 October 2026. It is useful as a cross-check, not as the brand's official master catalog.

The official store's all-products page currently reports 129 products, while its fragrance-only collection reports 74 products. Those figures have different scope and pagination and must not be treated as directly comparable perfume-identity counts. The official site also has room sprays/home-fragrance products, which are not perfumes.

## Reconciliation result

- ScentHunter seed: 120 canonical Maison Asrar identities.
- Independent EU reference: 116 perfume names.
- Reference coverage: all 116 names match an existing canonical identity or alias in ScentHunter.
- Four additional identities in ScentHunter beyond the 116-name reference:
  - Black Grapefruit — listed in Maison Asrar's official all-products collection.
  - Plot Twist — Gulf Orchid product page explicitly labels the brand Maison Asrar and states 100 ml EDP.
  - Love Key — Gulf Orchid product page explicitly labels the brand Maison Asrar and states 100 ml EDP.
  - Unsolved Mystery — Gulf Orchid product page explicitly labels the brand Maison Asrar and states 100 ml EDP.

No new canonical products are added by this audit because all 116 reference names and all four additional identities are already present in the seed. No duplicate identities are created.

## Data-quality finding: variants

The 120 Maison Asrar identities currently have only three explicit variant rows: Plot Twist, Love Key and Unsolved Mystery (100 ml EDP). Most entries are name-level records and do not yet have confirmed size/concentration variants in the structured variant table.

This does not mean the perfumes have no variants; it means the current seed does not yet carry enough verified detail to create those variant rows safely. The next improvement for Maison Asrar should be a separate detail-page/variant harvest, using official brand product pages first and trusted retailer product pages only as supporting evidence.

## Validation limits

- The 116-name reference is independent, not official.
- The official brand collection is dynamic and reports a different number because it includes a different scope of products and may paginate.
- This audit confirms name coverage against the 116-name reference, not worldwide historical completeness, current availability, or completeness of size/concentration variants.
- Room sprays and reed diffusers remain outside the perfume catalog scope.
