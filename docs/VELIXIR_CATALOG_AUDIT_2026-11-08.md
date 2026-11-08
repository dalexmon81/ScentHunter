# Velixir catalog audit — 2026-11-08

## Result

The brand's own stores list **28 individual perfumes**: 24 Eau de Parfum and four Extrait de Parfum (Comus, Ether, Orpheus and Panacea). All 28 identities already existed in ScentHunter; the gap was that no bottle/sample variants had been recorded.

The brand's UK storefront shows four sizes for the individual products: 100 ml, 35 ml, 3 ml sample and 2 ml vial. The brand's Indonesian storefront product pages independently confirm 35 ml and 100 ml on the EDP products. The UK official product pages show the 3 ml sample and 2 ml vial options, including for the Extrait range.

## Catalog changes

- Preserve all 28 existing canonical identities; no new perfume names were required.
- Add 4 size variants to each perfume: 2, 3, 35 and 100 ml.
- Total: 112 explicit variants (96 for the 24 EDPs and 16 for the four Extraits).
- Update product source URLs to individual brand product pages.
- Record the UK brand collection page as variant-size evidence.
- Keep discovery sets and bundles out of the canonical perfume catalog: they are multi-product sets, not individual fragrances.

## Concentration split

### Eau de Parfum (24)
Adonis, Aphrodite, Apollo, Ares, Artemis, Asteria, Athena, Concordia, Demeter, Galatea, Harmonia, Helios, Hera, Himeros, Icarus, Morpheus, Narcisus, Nyx, Orion, Paladin, Persephone, Poseidon, Selene, Uranus.

### Extrait de Parfum (4)
Comus, Ether, Orpheus, Panacea.

## Sources

- Brand's Indonesian storefront: https://velixirparfums.com/collections/all
- Brand's UK storefront: https://velixir.co.uk/collections/all
- Brand's UK Extrait collection: https://velixir.co.uk/collections/velixir-extrait-de-parfum
- Example EDP detail page (sizes 100, 35, 3 ml sample, 2 ml vial): https://velixir.co.uk/products/adonis-eau-de-parfum-by-velixir-parfums
- Example Extrait detail page (sizes 100, 35, 3 ml sample, 2 ml vial): https://velixir.co.uk/products/panacea

## Exclusions

The Discovery Set, Sacred Four Bundle and JTC Bundle are not individual fragrances and are not counted as canonical perfume identities. They can be modelled later as sets if ScentHunter adds a bundle/product-set feature.

## Validation targets

- 28 canonical Velixir identities in product_catalog.json and family_registry.json.
- 112 variants, with no duplicate IDs or orphan records.
- Each variant has concentration and size supported by brand storefront evidence.
