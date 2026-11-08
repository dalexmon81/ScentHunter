# Catalog expansion — requested fragrance houses

Scope: add canonical catalogue identities only. Do not create retailer offers, prices, stock, GTINs, URLs, or timestamps from catalogue research. Product variants (concentration, size, tester/refill/gift set) must remain separate and only be emitted when a source explicitly identifies them.

## Research sources and verified scope

| Brand / line | Scope found | Source |
|---|---|---|
| Velixir | Official collection page; 30 products listed. Names surfaced include Adonis, Aphrodite, Apollo, Ares; separate sizes 100/35/3/2 ml and EDP label shown. | https://velixirparfums.store/collections/all |
| Mykonos | Official collections list 100 ml (26), 50 ml (37), and categories; brand identifies itself as Indonesian. | https://officialmykonos.com/collections |
| Maison Asrar | European catalogue lists 116 fragrances; official Royal Collection page lists 9 products. | https://maisonasrarperfumes.eu/fr/perfumes/ ; https://maisonasrar.com/collections/royal-collection |
| Khadlaj | Official collections directory includes extensive named collections and product counts. | https://khadlaj-perfumes.com/collections |
| Bujairami | Independent EU guide reports 1,222 names listed by brand on 2026-11-05; its own dataset covers 1,207. Not an official source: must import as third-party-sourced records and flag provenance. | https://bujairamiperfumes.eu/ |
| Paris Corner | Official all-products collection page is available. | https://www.pariscornerperfumes.com/collections/all |
| Assaf | Catalogue lists 140 scents. | https://assafperfumes.eu/perfumes/ |
| Al Wataniah | Official site exposes Classic Collection and current launches. | https://www.alwataniah.com/ |
| Armaf | Official All Fragrances collection includes 248 Eau de Parfum entries plus other perfume formats; exclude body care/accessories from perfume-only ingestion. | https://armaf.com/collections/all-perfumes |
| French Avenue | Official collections page includes Aromatix Collection and other ranges. | https://frenchavenue.com/products/ |
| Arabiyat Prestige | Official site lists named products and series. | https://arabiyatprestige.com/ |
| Gulf Orchid | Official collections page includes multiple fragrance collections. | https://shop-gulforchid.com/collections |
| Swiss Arabian | Official source not confirmed in this research batch; keep queued for source discovery, do not seed guessed data. | |
| Games of Spades (Jo Milano) | Retailer collection lists 77 products including Full House, Opal, Moon, Emerald, Boston, Double Bonus, Bonus; includes gift sets, which must be separate product types. | https://www.jperfumeusa.com/collections/game-of-spade |
| Lattafa | Collection page lists 283 products, including Lattafa and Lattafa Pride; includes non-perfume formats that require filtering. | https://www.lattafa-usa.com/collections/all |
| Afnan | Official site exposes collections including 9AM/9PM, Supremacy, Bouquet, Historic, Kiaana, Modest, Mirsaal, Lynked, Tribute, Turathi, Edict, Rare, etc. | https://afnan.com/ |
| Aromatix | Aromatix X French Avenue already appears in repository family registry. Retail catalogue shows 10 Aromatix X French Avenue items; verify exact identity and do not duplicate as a manufacturer brand absent brand metadata. | https://shoparomatix.com/collections/all-products |
| Maison Alhambra | No authoritative exhaustive source verified in this batch; add source discovery task before ingestion. | |
| Zimaya | No authoritative exhaustive source verified in this batch; add source discovery task before ingestion. | |
| Al Haramain | Official EU collection lists 198 items across 5 pages; page 1 shows products such as Junoon, Amber Oud Ruby Edition, Amber Oud Gold Edition Extreme, L'Aventure Grapefruit/Iris/Ciel, Detour Noir. | https://shop.alharamainperfumes.com/eu/collection.html |

## Important catalogue rules

1. The word “all” means all items discoverable from a maintained source, not a hand-written sample. Use pagination/API/feed or official collection enumeration and retain source URL, source type, retrieval timestamp, and source version/hash.
2. Keep source provenance at the product record level. Official brand source outranks authorized retailer; retailer/third-party catalogues must be flagged as such.
3. Do not map product inspiration/dupe claims to the referenced original fragrance brand.
4. Exclude gift sets, samples, discovery sets, oils, deodorants, home fragrance and body care from perfume SKUs unless the existing catalogue explicitly models those as separate product types.
5. Never infer GTIN, concentration, size, gender, stock, price, or variant from an image/name alone. Null unknown fields and put ambiguous items in review.
6. Deduplicate on GTIN when verified; otherwise use normalized brand + fragrance + concentration + size + format. Preserve different concentrations/sizes/tester/refill/gift-set variants.
7. Do not insert commercial offers from these sources. This task is catalogue enrichment only and does not change the Liquid Brun live-offer acceptance test.

## Work remaining before merge

- Enumerate every page/item for each source, with raw response snapshots in fixtures.
- Add exact products to the canonical product/variant import format; validate schema and duplicate behavior.
- Resolve outstanding authoritative-source tasks for Swiss Arabian, Maison Alhambra and Zimaya.
- Confirm brand identity and whether Aromatix is a co-branded collection or standalone brand in each relevant record.
- Run import dry-run, compare before/after counts, and inspect collisions/ambiguous variants.
- Keep PR #424 open and unmerged; no production changes.
