# Verified Swiss Arabian and Zimaya additions — 2026-11-08

## Result

The catalog was compared against the first-party discovery candidates in the preceding audit and the current canonical seed. Fifteen previously absent fragrance identities were confirmed from individual official product pages and added with explicit variants. Ten additional existing Zimaya identities (including Ghali Elegante) were upgraded from discovery-only to product-page-verified provenance with explicit variants.

- Swiss Arabian: 4 new identities.
- Zimaya: 11 new identities (including one concentrated perfume oil, kept distinct from EDP spray products); 9 existing Zimaya identities upgraded with verified official detail pages and 100 ml EDP variants.
- Zimaya Ghali Elegante: retained as one canonical identity; official storefront spelling "Ghali Elegant" added as an alias.
- No Afnan or Bujairami additions were made in this pass because the reviewed candidates already matched existing canonical identities or aliases.
- No gift sets, deodorants, body sprays, room sprays, or retailer offers were added.

## Swiss Arabian — verified product pages and variants

| Canonical identity | Official product page | Explicit variant evidence |
|---|---|---|
| Shaghaf Nectar Blush | https://swissarabian.com/products/shaghaf-nectar-blush | 75 ml Eau de Parfum — https://us.swissarabian.com/ |
| Patchouli 01 | https://swissarabian.com/products/patchouli-01 | 50 ml Extrait de Parfum — https://us.swissarabian.com/ |
| Shaghaf Oud Marine | https://swissarabian.com/products/shaghaf-oud-marine | 75 ml Eau de Parfum — https://us.swissarabian.com/ |
| Echoes of St. Moritz | https://swissarabian.com/products/echoes-of-st-moritz | 100 ml Extrait de Parfum — https://us.swissarabian.com/ |

The official product pages identify the individual fragrances and provide their descriptions. The official US storefront exposes the explicit size and concentration in each product listing. The Collector's Edition III page independently confirms the 100 ml Extrait for Echoes of St. Moritz and 75 ml EDP for Shaghaf Oud Marine; the set itself was not imported as a fragrance identity.

## Zimaya — verified product pages and variants

| Canonical identity | Official product page | Explicit variant |
|---|---|---|
| Siada Regal | https://us.zimayaperfumes.com/products/siada-regal-perfume | 100 ml EDP, Unisex |
| Siada Nova | https://us.zimayaperfumes.com/products/siada-nova-perfume | 100 ml EDP, Unisex |
| Nojoum | https://us.zimayaperfumes.com/products/nojoum-perfume-oil | 20 ml Concentrated Perfume Oil, Unisex |

Nojoum is explicitly a concentrated perfume oil (CPO), not an EDP spray. It is retained as a separate fragrance format and is not mislabeled as Eau de Parfum.

## Existing identity spelling reconciliation

The official Zimaya product page uses "Ghali Elegant" and confirms 100 ml EDP for women. The catalog already had the identity "Ghali Elegante". To avoid creating a duplicate, the canonical identity remains unchanged and "Ghali Elegant" is added as an official alias. The existing identity is upgraded to product-page-verified provenance and receives its explicit 100 ml EDP variant.

## Additional Zimaya product-page verification

Nine more entries already present as discovery-only names were upgraded using their individual official US product pages. Each page identifies a 100 ml Eau de Parfum:

| Canonical identity | Official product page |
|---|---|
| Kibria Glory | https://us.zimayaperfumes.com/products/kibria-glory |
| Ode to Rose Royale | https://us.zimayaperfumes.com/products/ode-to-rose-royale |
| Ode to Rose Bella | https://us.zimayaperfumes.com/products/ode-to-rose-bella |
| Ghali Imperial | https://us.zimayaperfumes.com/products/ghali-imperial |
| Modhesh Noble | https://us.zimayaperfumes.com/products/modhesh-noble-perfume |
| Al Embratur Absolu | https://us.zimayaperfumes.com/products/al-embratur-absolu-perfume |
| Daiman Eclipse | https://us.zimayaperfumes.com/products/daiman-eclipse-perfume |
| Daiman Eden | https://us.zimayaperfumes.com/products/daiman-eden-perfume |
| Sharaf Divine | https://us.zimayaperfumes.com/products/sharaf-divine-perfume |

These are not nine additional canonical identities; they are nine existing identities whose provenance and exact 100 ml EDP variant are now verified. The product IDs remain unchanged.

## Further Zimaya sitemap reconciliation

Eight additional fragrances were present in the official Zimaya product sitemap and had individual official product pages. Their pages specify 100 ml Eau de Parfum:

| Canonical identity | Official product page |
|---|---|
| Modhesh Aura | https://us.zimayaperfumes.com/products/modhesh-aura-edp-100ml-perfume |
| Ramsh Diva | https://us.zimayaperfumes.com/products/ramsh-pour-femme-edp-100ml-perfume |
| Ramsh Imperium | https://us.zimayaperfumes.com/products/ramsh-imperium-edp-100ml-perfume |
| Sawalif Helwa | https://us.zimayaperfumes.com/products/sawalif-helwa-100ml-edp |
| Royal Paragon | https://us.zimayaperfumes.com/products/royal-paragon-edp-100ml-perfume |
| Roses Are White | https://us.zimayaperfumes.com/products/roses-are-white-edp-100ml-perfume |
| Rose Of Dreams | https://us.zimayaperfumes.com/products/rose-of-dreams-edp-100ml |
| Reflect | https://us.zimayaperfumes.com/products/reflect-edp-100ml-perfume |

The pages identify the products and their exact 100 ml EDP format. These eight identities were absent from the current catalog and are added as canonical products with one explicit 100 ml variant each. PR boxes and other non-fragrance items from the sitemap were excluded.

## Reconciliation and safety

- All seven new candidate identities were checked against existing canonical names and aliases before insertion.
- Nine pre-existing Zimaya identities were matched to the official US product pages and given 100 ml EDP variants without changing their canonical product IDs.
- Product IDs and variant IDs are unique in the seed.
- Each new variant references its canonical product and its size is reflected in the parent `formats_ml`.
- No price, availability, stock, shipping, GTIN, or retailer offer was added.
- Existing PRs #424, #437, #439 and discovery PR #541 remain unmerged and untouched.
- This PR is stacked directly on #439 and does not target `main`.

## Source references

- Swiss Arabian official product pages: the four URLs in the Swiss Arabian table above.
- Swiss Arabian official US storefront: https://us.swissarabian.com/
- Swiss Arabian official Collector's Edition III detail page: https://swissarabian.com/products/the-collectors-edition-iii
- Zimaya official individual pages: the three URLs in the Zimaya table above.
- Zimaya official collection pages were used only for candidate discovery, not as a substitute for individual product provenance.
