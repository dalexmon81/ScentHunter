# Al Wataniah Classic official product variants — 8 November 2026

## Scope

This pass upgrades eight existing Al Wataniah Classic collection identities to individual pages on the brand-owned Al Wataniah storefront. Each inspected page explicitly states Eau de Parfum and 100 ml.

## Verified records

| Existing identity | Official page | Verified format |
|---|---|---|
| Milele | https://www.alwataniah.com/products/milele | 100 ml Eau de Parfum |
| Turquois | https://www.alwataniah.com/products/turquois | 100 ml Eau de Parfum |
| Cloud | https://www.alwataniah.com/products/cloud | 100 ml Eau de Parfum |
| Crème | https://www.alwataniah.com/products/creme | 100 ml Eau de Parfum |
| Sabah Al Ward | https://www.alwataniah.com/products/sabah-al-ward | 100 ml Eau de Parfum |
| Sabah Al Ward Sugar | https://www.alwataniah.com/products/saba-al-ward-sugar | 100 ml Eau de Parfum |
| Special Oud | https://www.alwataniah.com/products/special-oud | 100 ml Eau de Parfum |
| Attar Al Wesal | https://www.alwataniah.com/products/attar-al-wesal | 100 ml Eau de Parfum |

## Catalog changes

- Existing canonical product IDs are preserved.
- Individual product pages replace collection-listing URLs in `source_url` and `source_evidence_url`.
- All eight records are marked `source_verified_name`.
- Each receives `formats_ml: [100]`, concentration `Eau de Parfum`, and one matching 100 ml variant.
- The Al Wataniah family registry is aligned.
- No prices, offers, stock, shipping, or availability are imported.

## Snapshot after this pass

- Canonical identities: 2,074 (unchanged)
- Total variants: 349
- Al Wataniah identities: 86 (unchanged)
- Al Wataniah variants: 19

## Regression protection

The existing `backend/tests/test_al_wataniah_official_collection_harvest.py` is extended to validate the eight additional official product pages and variants.
