# Khadlaj catalog audit — 2026-11-08

## Scope and result

The official Khadlaj Perfumes store has a dedicated **Perfume Sprays** collection. Its page currently reports 101 products. The static page extraction exposes 96 product cards across the first eight loads; all 96 visible perfume names are now matched to ScentHunter.

One visible product was missing as a canonical identity: **Private Blend Tobac Extra Extrait de Parfum 100 ml**. It has been added as a separate perfume, not merged into the existing generic Private Blend. The official product page gives its name, 100 ml size, concentration and EAN/SKU details.

The current visible listing also spells the product **SENSUOS NIGHT**, while the product description uses **Sensuous Night**. ScentHunter keeps the canonical name Sensuous Night and adds Sensuos Night as an alias.

## Catalog changes

- Previous Khadlaj identities: 116.
- New canonical product added: Private Blend Tobac Extra.
- Khadlaj identities after this audit: **117**.
- 96 visible official perfume-spray products now have explicit size/concentration variants.
- The 5 products implied by the collection's 101-item count but not exposed in the page extraction remain pending; this audit does not claim full parity with all 101.
- The remaining catalog names outside the visible 96 may include older releases and products in other collections; they have not been deleted.

## Product types kept separate

The official site has separate navigation for La Fede, perfume oils, home and ambiance, bakhoor, and gift sets. These are not automatically merged into the Khadlaj perfume-spray list. Three La Fede Celebrity products already appear in the Khadlaj seed; the wider La Fede range is a separate sub-brand audit still to do.

## Sources

- Official Khadlaj Perfumes store: https://khadlaj-perfumes.com/
- Official Perfume Sprays collection: https://khadlaj-perfumes.com/collections/perfumes-spray
- Private Blend Tobac Extra product page: https://khadlaj-perfumes.com/collections/perfumes-spray/products/private-blend-tobac-extra-extrait-de-parfum-100-ml-for-men
- Sensuos Night product page: https://khadlaj-perfumes.com/collections/perfumes-spray/products/sensous-night-edp-spray-shop-online-best-price-in-dubai-uae
- Separate La Fede collection/navigation: https://khadlaj-perfumes.com/collections/la-fede

## Variant evidence

The 96 visible collection cards provide product names, sizes and concentration labels. Their source page is recorded by page number in each variant's `source_evidence_url`. The product page for Private Blend Tobac Extra and the product page for Sensuos Night are recorded individually.

## Open work

1. Retrieve the five collection items not exposed by the static page extraction and compare them with the catalog.
2. Audit the La Fede sub-brand as a separate range before deciding whether to reclassify the three La Fede items currently stored under Khadlaj.
3. Audit the separate perfume-oil and home-fragrance ranges only if they are in scope for ScentHunter.
