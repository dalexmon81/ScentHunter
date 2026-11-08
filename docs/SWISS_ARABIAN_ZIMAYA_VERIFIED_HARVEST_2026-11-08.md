# Verified Swiss Arabian and Zimaya additions — 2026-11-08

## Result

The catalog was compared against the first-party discovery candidates in the preceding audit and the current canonical seed. Seven previously absent fragrance identities were confirmed from individual official product pages and added with explicit variants. One existing Zimaya identity was corrected with an official spelling alias and its verified product page/variant.

- Swiss Arabian: 4 new identities.
- Zimaya: 3 new identities (including one concentrated perfume oil, kept distinct from EDP spray products).
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

## Reconciliation and safety

- All seven candidate identities were checked against existing canonical names and aliases before insertion.
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
