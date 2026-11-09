# Afnan 9AM/9PM official detail verification — 9 November 2026

## Verified identities

The official Afnan Perfumes Europe storefront product pages explicitly identify the following 100 ml variants:

| Existing canonical product | Concentration | Official detail page |
|---|---|---|
| 9 PM Night Out | Extrait de Parfum | https://www.fr.afnan.com/en/products/9pm-night-out |
| 9 PM Elixir | Extrait de Parfum | https://www.fr.afnan.com/en/products/9-pm-elixir |
| 9 PM Pour Femme | Eau de Parfum | https://www.fr.afnan.com/en/products/9-pm-pour-femme |
| 9 AM | Eau de Parfum | https://www.fr.afnan.com/en/products/9-am |
| 9 AM Pour Femme | Eau de Parfum | https://www.fr.afnan.com/en/products/9-am-pour-femme |
| 9 AM Dive | Eau de Parfum | https://www.fr.afnan.com/en/products/9-am-dive |
| 9 PM Rebel | Eau de Parfum | https://www.fr.afnan.com/en/products/9-pm-rebel |
| 9 PM | Eau de Parfum | https://www.fr.afnan.com/en/products/9-pm |

## Catalog handling

- All eight existing canonical product IDs were preserved.
- The 9PM Night Out and 9PM variants were retained and their official evidence URLs synchronized.
- Six missing 100 ml variants were added for the remaining existing identities.
- Eau de Parfum and Extrait de Parfum remain distinct concentrations.
- No gift sets, deodorants, oils, retailer offers, prices, stock, GTINs, MPNs or affiliate data were inferred or imported.

## Validation

The dedicated regression module checks all eight product identities, their 100 ml variants, exact official evidence URLs and concentration separation.

Workflow note: the stacked PR validation workflow on the target catalog branch explicitly includes this PR's base branch.


# Afnan Supremacy official detail verification — 9 November 2026

## Verified official product pages

| Existing canonical identity | Concentration | Verified volume(s) | Official product page |
|---|---|---:|---|
| Supremacy Gold | Eau de Parfum | 100 ml | https://www.fr.afnan.com/en/products/supremacy-gold |
| Supremacy Silver | Eau de Parfum | 100, 150 ml | https://www.fr.afnan.com/en/products/supremacy-silver |
| Supremacy Collector's Edition | Eau de Parfum | 100 ml | https://www.fr.afnan.com/en/products/supremacy-collectors-edition |
| Supremacy Pink | Eau de Parfum | 100 ml | https://www.fr.afnan.com/en/products/supremacy-pink |
| SUPREMACY TAPIS ROUGE - LUXURY COLLECTION | Extrait de Parfum | 90 ml | https://www.fr.afnan.com/en/products/supremacy-tapis-rouge |
| Supremacy Not Only Intense | Extrait de Parfum | 100, 150 ml | https://www.fr.afnan.com/en/products/supremacy-not-only-intense |
| Supremacy Purple | Eau de Parfum | 100 ml | https://www.fr.afnan.com/en/products/supremacy-purple |

## Catalog handling

- Seven existing canonical identities were preserved.
- Seven explicit variants were added; the existing Supremacy Not Only Intense 100 ml and 150 ml variants were retained and linked to their official detail evidence.
- Supremacy Silver remains available as distinct 100 ml and 150 ml variants.
- Supremacy Tapis Rouge is represented as a 90 ml Extrait de Parfum, not normalized to 100 ml.
- Eau de Parfum and Extrait de Parfum remain distinct.
- No prices, stock, gift-set contents, retailer offers, GTINs, MPNs or affiliate data were inferred or imported.

## Validation

The existing Afnan/Lattafa official-harvest test module now verifies all seven Supremacy identities and each explicitly listed volume/concentration combination.
