# Lattafa official missing-identity reconciliation — 8 November 2026

## Scope

Nine identities already present in the `lattafa_catalog` family registry were absent from the canonical product seed. They are now promoted using individual pages from Lattafa's brand-owned global site (`lattafa.com`) and official US store (`lattafa-usa.com`). The US store product pages identify the shop as supplying authentic fragrances directly from Lattafa.

## Added products and variants

| Canonical identity | Size | Concentration |
|---|---:|---|
| Ana Abiyedh Rouge | 60 ml | Eau de Parfum |
| Rave Now White | 100 ml | Eau de Parfum |
| 24 Carat White Gold | 100 ml | Eau de Parfum |
| Ajayeb Dubai Portrait | 100 ml | Eau de Parfum |
| Al Dur Al Maknoon Silver | 100 ml | Eau de Parfum |
| Al Nashama | 100 ml | Eau de Parfum |
| Ameer Al Oud Intense | 100 ml | Eau de Parfum |
| Ana Abiyedh Coral | 60 ml | Eau de Parfum |
| GMG Whipped Pleasure | 75 ml | Eau de Parfum |

Official product pages:
- Ana Abiyedh Rouge: https://lattafa.com/product/ana-abiyedh-rouge/
- Rave Now White: https://lattafa.com/product/rave-now-white/
- 24 Carat White Gold: https://lattafa.com/product/24-carat-white-gold/
- Ajayeb Dubai Portrait: https://lattafa.com/product/ajayeb-dubai-portrait/
- Al Dur Al Maknoon Silver: https://lattafa.com/product/al-dur-al-maknoon-silver/
- Al Nashama: https://www.lattafa-usa.com/products/al-nashama
- Ameer Al Oud Intense: https://lattafa.com/product/ameer-al-oudh-intense/
- Ana Abiyedh Coral: https://lattafa.com/product/ana-abiyedh-coral/
- GMG Whipped Pleasure: https://lattafa.com/product/whipped-pleasure/

For Ana Abiyedh Rouge, Ana Abiyedh Coral, Al Nashama, Ameer Al Oud Intense, and GMG Whipped Pleasure, the official US store product page is also recorded in `source_evidence_url` where it supplies the explicit EDP/size details. Other records use the global brand page as both source and evidence.

## Identity and spelling guardrails

- `Ajayab Dubai Portrait` is retained as an alias of the official spelling `Ajayeb Dubai Portrait`.
- `Ameer Al Oudh Intense` and `Ameer Al Oudh – Intense` are aliases of the registry identity `Ameer Al Oud Intense`.
- `GMG Whipped Pleasure` remains the canonical registry name; `Whipped Pleasure` and `Give Me Gourmand Whipped Pleasure` are aliases.
- `Al Nashama` is kept distinct from `Al Nashama Caprice`. The latter is a separate product on the global site; no merge is made.

## Catalog changes

- Adds nine canonical identities and nine matching variants.
- Updates the existing `lattafa_catalog` registry rows with explicit sizes.
- No prices, retailer offers, stock, or availability snapshots are copied.

## Snapshot after change

- Lattafa canonical products: 123
- Lattafa variants: 13
- Total canonical products: 2,149
- Total variants: 395

## Regression protection

`backend/tests/test_lattafa_official_missing_identities.py` checks the nine official product pages, sizes, EDP variants, family-registry format alignment, spelling aliases, and ID uniqueness.
