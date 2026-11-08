# Al Wataniah official 100 ml EDP variants — third pass — 8 November 2026

## Scope

This pass upgrades six more existing Al Wataniah identities to individual pages on the brand-owned storefront. Each page explicitly confirms Eau de Parfum and 100 ml.

## Verified records

| Existing identity | Official page | Verified format |
|---|---|---|
| Lazuli | https://www.alwataniah.com/products/lazuli | 100 ml Eau de Parfum |
| Sahari | https://www.alwataniah.com/products/sahari | 100 ml Eau de Parfum |
| Layali | https://www.alwataniah.com/products/layali | 100 ml Eau de Parfum |
| Nawal Alexandrite | https://www.alwataniah.com/products/nawal-alexandrite | 100 ml Eau de Parfum |
| Fayyad | https://www.alwataniah.com/products/fayyad | 100 ml Eau de Parfum |
| Nawal Bronzite | https://www.alwataniah.com/products/nawal-bronzite | 100 ml Eau de Parfum |

## Catalog changes

- Existing canonical product IDs are preserved.
- Individual official pages replace collection-listing URLs in `source_url` and `source_evidence_url`.
- All six records are marked `source_verified_name`.
- Each receives `formats_ml: [100]`, concentration `Eau de Parfum`, and one matching 100 ml variant.
- The Al Wataniah family registry and regression test are aligned.
- No prices, offers, stock, shipping, or availability are imported.

## Snapshot after this pass

- Canonical identities: 2,074 (unchanged)
- Total variants: 363
- Al Wataniah identities: 86 (unchanged)
- Al Wataniah variants: 33

## Regression protection

The existing `backend/tests/test_al_wataniah_official_collection_harvest.py` now validates these six additional official product pages and variants.
