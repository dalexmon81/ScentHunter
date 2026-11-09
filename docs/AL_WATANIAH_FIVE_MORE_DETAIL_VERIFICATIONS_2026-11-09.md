# Al Wataniah — five additional official detail-page verifications (9 November 2026)

## Scope

Five existing canonical identities were checked against their individual product pages on the brand-owned Al Wataniah storefront. Each inspected page explicitly identifies the item as Eau de Parfum and states a 100 ml volume.

| Existing identity | Official detail page | Explicit specification |
|---|---|---|
| Abyat | https://www.alwataniah.com/products/abyat | Eau de Parfum, 100 ml |
| Ameerati | https://www.alwataniah.com/products/ameerati | Eau de Parfum, 100 ml |
| Baraa | https://www.alwataniah.com/products/baraa | Eau de Parfum, 100 ml |
| Al Layl | https://www.alwataniah.com/products/al-layl | Eau de Parfum, 100 ml |
| Alya | https://www.alwataniah.com/products/alya | Eau de Parfum, 100 ml |

## Data handling

- All five existing canonical product IDs were preserved.
- No duplicate canonical identities were created.
- Each product's evidence was upgraded to `source_verified_name` and points to its individual official detail page.
- One 100 ml Eau de Parfum variant was added per product, with a unique deterministic variant ID and its own `source_evidence_url`.
- The existing Al Wataniah family registry was synchronized with the explicit 100 ml formats.
- No prices, stock, retailer offers, shipping, GTINs, MPNs or affiliate data were imported.
- Temporary sold-out and promotional states on the storefront were not copied into the canonical catalog.

## Validation

The catalog seed workflow includes both Al Wataniah regression modules. The collection-harvest test now expects nine explicit Al Wataniah variants in total: the original Lemon Souffle and Choco Truffle variants, Ameeri and Sultan Al Lail from the preceding update, and these five additional verified variants.
