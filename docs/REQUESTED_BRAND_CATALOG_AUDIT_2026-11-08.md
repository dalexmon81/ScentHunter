# Requested Brand Catalog Audit — 2026-11-08

## Scope and method

This audit inspects the canonical `backend/product_catalog.json` on the consolidated catalog branch. It counts distinct catalog rows by `brand_name`, groups each row by `identity_status`, and records the host of its `source_url`.

- `source_verified_name` and `source_listed_name` are the catalog's existing evidence labels. They describe the identity's recorded evidence state; they do not, by themselves, prove that the source domain is brand-owned.
- A source URL is present for every identity counted below.
- Counts are canonical fragrance identities, not SKU/variant counts.
- This is a snapshot audit, not proof that every historic, regional, limited-edition or newly released perfume worldwide has been captured.

## Requested brand coverage

| Brand | Identities | source_verified_name | source_listed_name |
|---|---:|---:|---:|
| Velixir | 28 | 28 | 0 |
| Mykonos | 72 | 0 | 72 |
| Maison Asrar | 120 | 12 | 108 |
| Khadlaj | 116 | 3 | 113 |
| Bujairami | 142 | 20 | 122 |
| Paris Corner | 245 | 6 | 239 |
| Assaf | 140 | 0 | 140 |
| Al Wataniah | 86 | 2 | 84 |
| Armaf | 190 | 6 | 184 |
| French Avenue | 119 | 5 | 114 |
| Arabiyat Prestige | 118 | 22 | 96 |
| Gulf Orchid | 23 | 0 | 23 |
| Swiss Arabian | 32 | 4 | 28 |
| Games of Spades | 29 | 6 | 23 |
| Lattafa | 114 | 4 | 110 |
| Afnan | 87 | 0 | 87 |
| Aromatix | 12 | 0 | 12 |
| Maison Alhambra | 203 | 0 | 203 |
| Zimaya | 72 | 10 | 62 |
| Al Haramain | 101 | 0 | 101 |
| **Total requested brands** | **2,049** | **230** | **1,819** |

The full seed contains 2,052 identities. The remaining three belong to other brands (Al Ambra: 2; Giorgio Armani: 1) and are outside this requested-brand subtotal.

## Recorded source hosts

| Brand | Source hosts and row counts |
|---|---|
| Velixir | velixirparfums.com (28) |
| Mykonos | officialmykonos.com (72) |
| Maison Asrar | maisonasrar.com (117); shop-gulforchid.com (3) |
| Khadlaj | khadlaj-perfumes.com (116) |
| Bujairami | bujairami.ae (117); bujairami.com.au (21); bujairami.eu (4) |
| Paris Corner | www.pariscornerperfumes.com (245) |
| Assaf | assafperfumes.eu (119); assaf.ae (21) |
| Al Wataniah | www.alwataniah.com (86) |
| Armaf | armaf.com (190) |
| French Avenue | frenchavenue.com (79); www.fragrantica.com (40) |
| Arabiyat Prestige | www.fragrantica.com (93); eu.myperfumes.ae (22); arabiyatprestigeus.com (2); arabiyatprestige.com (1) |
| Gulf Orchid | shop-gulforchid.com (23) |
| Swiss Arabian | swissarabian.ma (27); us.swissarabian.com (3); de.swissarabian.com (1); www.essenciaarabe.com (1) |
| Games of Spades | jomilanoparis.com (29) |
| Lattafa | lattafa.com (90); lattafaparfum.eu (23); www.essenciaarabe.com (1) |
| Afnan | afnan.com (83); www.afnaneurope.com (4) |
| Aromatix | www.notino.be (12) |
| Maison Alhambra | maisonalhambra-usa.com (203) |
| Zimaya | zimayaperfumes.com (72) |
| Al Haramain | shop.alharamainperfumes.com (101) |

## Priority evidence gaps

1. **Independent / retailer-heavy discovery:** Assaf is entirely listing-backed in this snapshot; the PR #437 notes that its 119-name harvest uses an independent range index. French Avenue includes 43 Fragrantica-sourced names. Arabiyat Prestige includes 93 Fragrantica-sourced names. Aromatix's 12 rows currently point to Notino.
2. **Listing-level evidence dominates:** Paris Corner, Maison Alhambra, Afnan, Al Haramain, Mykonos, Gulf Orchid and several other brands have no `source_verified_name` rows in this snapshot. This is not proof that the names are wrong; it means individual product-page verification is the next quality step.
3. **Regional/source reconciliation:** Bujairami, Swiss Arabian, Lattafa and Maison Asrar use multiple regional or retailer domains. Reconcile regional naming, retired products and aliases before treating these as a single globally exhaustive range.

## Collection-specific verification

### Maison Asrar Royal Collection

The official UAE collection page lists nine individual fragrances: Belgravia, Legacy, Vanguard, Regent, Majesty, Heritage, Monarch, Treasure and Imperial. All nine are present in the canonical seed.

The UK storefront lists "The Royal", but its product detail describes it as a bundle of Legacy, Majesty and Vanguard. It is therefore not a separate fragrance identity and must not be added as a tenth Royal Collection perfume.

Sources:
- https://maisonasrar.com/collections/royal-collection
- https://maisonasrar.co.uk/collections/royal-collection
- https://maisonasrar.co.uk/products/the-royal

### Aromatix signature collection

The official Aromatix signature collection page names ten fragrances: Teas Me, Frostbite, Naughty Dates, Sun Kissed, Forbidden Fruit, Magnetiq, Platine Blanc, X Xandal, Royal Taboo and Carnal Desire. All ten are present in the canonical seed. The catalog's two additional Aromatix names are retailer-listed and are not included in this official ten-fragrance signature list.

Source:
- https://shoparomatix.com/pages/aromatic-collection

## Next work

- Verify the listing-backed names against individual product pages where available.
- Promote evidence status only when the source actually supports it; preserve source URLs.
- Reconcile regional aliases and retired/discontinued products.
- Do not create duplicate canonical identities or infer sizes, concentrations, GTINs, offers, prices or stock.
- Keep all changes in draft PRs until tests and review are complete.


## Follow-up source comparison: Assaf and French Avenue

### Assaf

The current Assaf UAE storefront has an official "All perfumes" collection and separate official navigation for the Lady, Frankel, Arrogate and Enable collections. The first page currently exposes individual product listings such as Arrogate Pink, Attacks, Gris Erik, Miss Arrogate, Arrogate Pink Diva, Rebel Enable, Wild Colt Elixir, Arrogate Comete, Noble, First Night, Strike Black, I'm Here Enable, Frankel Imagination, Dangerous Arrogate, Arrogate Euphoria, Troy Enable, Addict Blue and Lip Stick.

The catalog currently has 140 Assaf identities. The 140-name range at assafperfumes.eu is explicitly described by that site's own disclaimer as an **independent reseller guide**, not the official Assaf website. It is useful for discovery and candidate reconciliation, but should not be cited as brand-owned evidence. The current Assaf UAE storefront is official and should be used to upgrade individual names only after each product detail page is checked.

Official collection:
- https://assaf.ae/collections/all-perfumes
- https://assaf.ae/collections/

Independent discovery reference (not official):
- https://assafperfumes.eu/perfumes/

### French Avenue

The official French Avenue storefront's `/collections/all` currently reports 142 products (141 in stock and one out of stock at the time inspected). Its separate "all fragrances for sale" collection reports 141 products. The first page visibly includes Liquid Brun, Liquid Brun Limited Edition, Spectre Ghost, Vulcan Feu, Azzure Aoud, Amber Empire, Dusk Till Dawn, Royal Blend Sequoia, Noble Cedar, Jasmere, Atlantis Extrait, Ambroise Pour Femme, Aether, Royal Blend, Imperial Ocean and Cocoa Morado.

The catalog previously contained 117 French Avenue identities. A full 2026 collection comparison showed that the storefront count includes product bundles/duplicate merchandising, so it cannot be used as a direct canonical identity count. Two additional standalone perfumes have since been confirmed on individual official product pages and added, bringing the brand total to 119.

Official storefront:
- https://frenchavenue.com/collections
- https://frenchavenue.com/collections/all
- https://frenchavenue.com/collections/all-fragrances-for-sale

Fragrantica's designer index reports 157 perfumes, including editions through 2026 and many collection names. It is a useful secondary discovery checklist, not a replacement for official product-page verification:
- https://www.fragrantica.com/designers/French-Avenue.html

### Immediate next verification tasks

1. Page through the complete official Assaf UAE perfume collection and compare each product detail URL against the existing 140 canonical identities. Do not use the independent 140-name list as proof of official completeness.
2. Page through all French Avenue official collection pages (including pagination and new arrivals), normalize only safe spelling/case aliases, and reconcile the product titles with the 117 current identities.
3. For any proposed addition, preserve the exact official product URL and record why it is a distinct fragrance rather than a size, concentration variant, bundle or renamed duplicate.
4. Do not change `identity_status` from `source_listed_name` to `source_verified_name` on the basis of a brand homepage or collection landing page alone.


### Manual page checks and false-positive prevention

- Assaf official collection page 2 shows existing identities such as Frankel Blackout, Noble, Frankel Ascot, Frankel Storm, Miss Sakura, Frankel Beach Afternoon, No Chance, Gris Flora, Pegasus Oud, Pink Lady, Frankel Afternoon, Troy Enable, Gris Erik, Miss Flora, Frankel Silver, Arrogate Addict Elixir, Glitch, Frankel Battle and Baby Girl. These are already represented in the 140-name catalog.
- Assaf official collection page 3 shows additional existing identities including Stand By, Pegasus Reflection, Feeling, Alex Enable, Hook Blue, Elizabeth, Error 404, Forever Here, Take Off, Greatness, Aura 30 and Pink Lady. These are also already represented.
- Page 3 also exposes "Arrogate Pink with Powder", but its official product page assigns SKU `PKG-ASFP50-ON-10101`. The `PKG` prefix and the product title indicate a package/bundle rather than a clean standalone perfume identity. It is deliberately **not** added as a new canonical fragrance pending clearer product composition evidence.
- The Assaf storefront also lists collection bundles such as "Enable Collection" and "Wild Pegasus and Alexandra Collection". These must not be counted as new perfume identities.

This spot-check confirms that the official storefront contains many of the existing catalog names and that naive harvesting of every store listing would introduce bundles/packages as false fragrance identities. The official collection is paginated and this is not yet an exhaustive crawl of all pages.


### Newly verified French Avenue additions (official product detail pages)

A comparison against the official New Arrivals collection found two standalone perfumes missing from the prior 117-identity seed. Both have individual official product pages, explicit 100 ml sizes and explicit concentrations:

| Canonical identity | Official detail page | Concentration | Size |
|---|---|---|---:|
| Eclipse | https://frenchavenue.com/products/eclipse | Extrait de Parfum | 100 ml |
| Eclipse Nova | https://frenchavenue.com/products/eclipse-nova-extrait | Extrait de Parfum | 100 ml |

Both were added as distinct canonical products with `source_verified_name`, exact product-page `source_url`, and explicit 100 ml variants. The French Avenue identity count is now 119; the full seed is now 2,052 products and 214 variants at this stage. Across the 20 requested brands the subtotal was 2,049 identities (227 `source_verified_name`, 1,822 `source_listed_name`) before the further official-page verifications below.

The official New Arrivals collection also displays **Aromatix Summer Vibes Blue** and **Aromatix Summer Vibes Yellow**. Their product detail pages describe each as a 5 × 30 ml set containing five existing Aromatix scents, not a new single fragrance. They were deliberately excluded from the canonical perfume identities; they may belong in a future kit/bundle model.

Official sources:
- https://frenchavenue.com/collections/new-arrivals
- https://frenchavenue.com/products/eclipse
- https://frenchavenue.com/products/eclipse-nova-extrait
- https://frenchavenue.com/products/aromatix-summer-vibes-blue
- https://frenchavenue.com/products/aromatix-summer-vibes-yellow

The latest 2026 discovery list on Fragrantica is retained as a secondary lead list only. Crystal Oud, Ethos Aoud Oud, Papa Yeah! and Les Extraits Absolus Shadow/Unknown remain listed-name candidates without individual official product-page evidence located in this pass. Le Falcon, Le Falcon Dubai and Spirito Ignite have now been verified against individual official product pages and upgraded below.


### Additional French Avenue official product-page verification

The following existing catalog identities were checked against their individual official product pages. Their source URLs now point directly to the official detail pages, their evidence status is `source_verified_name`, and the official size/concentration specifications are represented as explicit 100 ml variants:

| Canonical identity | Official detail page | Concentration | Size |
|---|---|---|---:|
| Le Falcon | https://frenchavenue.com/products/le-falcon | Eau de Parfum | 100 ml |
| Le Falcon Dubai | https://frenchavenue.com/products/le-falcon-dubai | Eau de Parfum | 100 ml |
| Spirito Ignite | https://frenchavenue.com/products/spirito-ignite | Extrait de Parfum | 100 ml |

These were already present as discovery identities, so no duplicate canonical products were created. The three official pages upgrade the evidence and variant completeness only.

Still not promoted: **Crystal Oud, Ethos Aoud Oud, Papa Yeah!, Les Extraits Absolus Shadow and Les Extraits Absolus Unknown**. The current secondary sources identify them as 2026 launches, but this check did not locate their individual official product detail pages. They remain discovery candidates and are not assigned invented sizes/concentrations.

Official pages checked:
- https://frenchavenue.com/products/le-falcon
- https://frenchavenue.com/products/le-falcon-dubai
- https://frenchavenue.com/products/spirito-ignite
- https://frenchavenue.com/collections/new-arrivals
