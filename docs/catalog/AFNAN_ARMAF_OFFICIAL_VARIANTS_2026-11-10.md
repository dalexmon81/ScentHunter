# Official Afnan and Armaf variant audit — 2026-11-10

## Official product-page evidence
- Afnan 9 AM — 100 ml Eau de Parfum: https://fr.afnan.com/products/9-am
- Afnan 9 AM Pour Femme — 100 ml Eau de Parfum: https://fr.afnan.com/products/9-am-pour-femme
- Afnan Rare — 100 ml Eau de Parfum: https://fr.afnan.com/products/rare
- Afnan Supremacy Gold — 100 ml Eau de Parfum: https://fr.afnan.com/products/supremacy-gold
- Afnan Stardust — 100 ml Extrait de Parfum: https://us.afnan.com/products/stardust
- Armaf Luna — 100 ml Eau de Parfum: https://cz.armaf.eu/products/luna
- Armaf Miss Armaf Attitude — 100 ml Eau de Parfum: https://cz.armaf.eu/products/miss-armaf-attitude
- Armaf Miss Armaf Grandeur — 100 ml Eau de Parfum: https://cz.armaf.eu/products/miss-armaf-grandeur
- Armaf Odyssey Candee Special Edition — 60, 100 and 200 ml Eau de Parfum: https://cz.armaf.eu/en/products/odyssey-candee-special-edition
- Armaf The Pride of Armaf Pour Homme — official US page lists 3.4 oz Eau de Parfum: https://armaf.com/products/the-pride-of-armaf-pour-homme

## Reconciliation
- Reuses existing canonical product IDs; adds no new product identities.
- Adds 12 explicit product-size-concentration variant rows.
- Does not invent GTINs.
- Synchronizes the corresponding family-registry formats.
- Adds no price, offer, retailer, stock, availability or shipping data.
- The Armaf US source uses 3.4 oz, not millilitres. The corresponding catalog 100 ml record is a nominal metric normalization, not a literal source value.

## Integrity
- Zero duplicate product IDs, variant IDs, normalized brand/name keys, product-size-concentration tuples and non-empty GTINs.
- Zero orphan variants.
- Exactly one family-registry mapping per canonical product.
