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
| Paris Corner | 245 | 7 | 238 |
| Assaf | 140 | 7 | 133 |
| Al Wataniah | 86 | 2 | 84 |
| Armaf | 190 | 6 | 184 |
| French Avenue | 119 | 6 | 113 |
| Arabiyat Prestige | 118 | 22 | 96 |
| Gulf Orchid | 23 | 0 | 23 |
| Swiss Arabian | 32 | 4 | 28 |
| Games of Spades | 29 | 6 | 23 |
| Lattafa | 114 | 4 | 110 |
| Afnan | 87 | 1 | 86 |
| Aromatix | 12 | 0 | 12 |
| Maison Alhambra | 207 | 6 | 201 |
| Zimaya | 77 | 15 | 62 |
| Al Haramain | 101 | 8 | 93 |
| **Total requested brands** | **2,057** | **157** | **1,900** |

The full seed contains 2,060 identities. The remaining three belong to other brands (Al Ambra: 2; Giorgio Armani: 1) and are outside this requested-brand subtotal.

## Recorded source hosts

| Brand | Source hosts and row counts |
|---|---|
| Velixir | velixirparfums.com (28) |
| Mykonos | officialmykonos.com (72) |
| Maison Asrar | maisonasrar.com (117); shop-gulforchid.com (3) |
| Khadlaj | khadlaj-perfumes.com (116) |
| Bujairami | bujairami.ae (117); bujairami.com.au (21); bujairami.eu (4) |
| Paris Corner | www.pariscornerperfumes.com (245) |
| Assaf | assafperfumes.eu (113); assaf.ae (27) |
| Al Wataniah | www.alwataniah.com (86) |
| Armaf | armaf.com (190) |
| French Avenue | frenchavenue.com (80); www.fragrantica.com (39) |
| Arabiyat Prestige | www.fragrantica.com (93); eu.myperfumes.ae (22); arabiyatprestigeus.com (2); arabiyatprestige.com (1) |
| Gulf Orchid | shop-gulforchid.com (23) |
| Swiss Arabian | swissarabian.ma (27); us.swissarabian.com (3); de.swissarabian.com (1); www.essenciaarabe.com (1) |
| Games of Spades | jomilanoparis.com (29) |
| Lattafa | lattafa.com (90); lattafaparfum.eu (23); www.essenciaarabe.com (1) |
| Afnan | afnan.com (83); de.afnan.com (1); www.afnaneurope.com (3) |
| Aromatix | www.notino.be (12) |
| Maison Alhambra | maisonalhambra-usa.com (207) |
| Zimaya | zimayaperfumes.com (74); de.zimayaperfumes.com (1); fr.zimayaperfumes.com (1); ro.zimayaperfumes.com (1) |
| Al Haramain | shop.alharamainperfumes.com (101) |

## Priority evidence gaps

1. **Independent / retailer-heavy discovery:** Assaf is entirely listing-backed in this snapshot; the PR #437 notes that its 119-name harvest uses an independent range index. French Avenue includes 43 Fragrantica-sourced names. Arabiyat Prestige includes 93 Fragrantica-sourced names. Aromatix's 12 rows currently point to Notino.
2. **Listing-level evidence dominates:** Paris Corner, Maison Alhambra, Al Haramain, Mykonos, Gulf Orchid and several other brands have no `source_verified_name` rows in this snapshot. This is not proof that the names are wrong; it means individual product-page verification is the next quality step.
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


### Additional French Avenue verification: Prune Hypnos

The existing canonical identity **Prune Hypnos** was checked against the official French Avenue product detail page:
- Product page: https://frenchavenue.com/products/prune-hypnos
- Official specifications: Eau de Parfum (EDP), 100 ml
- Catalog action: updated `source_url`, changed evidence status to `source_verified_name`, set concentration to `Eau de Parfum`, and added an explicit 100 ml EDP variant.
- No new canonical product was created; the existing identity was retained.

Note: some third-party retailers describe Prune Hypnos as Extrait de Parfum, but the official French Avenue product page specifies EDP. The catalog follows the brand's own product specification. The similarly named Fragrantica entry “Prune Hypnose” is not used to rename the official product.

Official source: https://frenchavenue.com/products/prune-hypnos


### Follow-up source review: additional 2026 candidates (8 November 2026)

A further source pass checked the remaining French Avenue candidates and possible new names. No additional canonical identities or variants were added in this pass because the available sources did not consistently establish brand-owned product specifications.

**Prune Hypnos — primary-source cross-check.** The official French Avenue page at https://frenchavenue.com/products/prune-hypnos explicitly specifies Eau de Parfum (EDP), 100 ml (page specifications section). The catalog's existing EDP/100 ml variant is therefore supported by the brand page. Some third-party listings call the same item Extrait; those conflicting reseller values are not used.

**Fleuriche Bisou Rose.** A French Avenue-branded regional page at https://french-avenue.ma/product/fleuriche-bisou-rose describes a 100 ml EDP, while distributor/retailer listings (including Novalux Europe) describe the EAN 6298042002487 as Extrait de Parfum, 100 ml. Since the accessible material does not resolve the concentration conflict against the primary global product page, this identity remains `source_listed_name` with no size/concentration variant added.

**Papa Yeah!** A French Avenue-branded regional page at https://french-avenue.ma/product/papa-yeah-extradose describes a 100 ml EDP, while distributor/retailer listings (EAN 6298042002753) describe Extrait de Parfum, 100 ml. A separate fragrance database also lists it as a 2026 launch, but is not a primary product specification source. It remains `source_listed_name` with no variant added pending a clear global brand product page or authoritative product feed.

**Crystal Oud, Ethos Aoud Oud, Les Extraits Absolus Shadow and Les Extraits Absolus Unknown.** These appear in fragrance databases as 2026 entries. For Ethos Aoud Oud, one database describes the fragrance as upcoming and explicitly states that size and bottle details are unknown. No individual official French Avenue product detail page or dependable primary specification was located in this pass. They remain discovery leads only.

**Additional discovery names.** Vulcan Vox and Arsh Black Ice appear in secondary fragrance-house databases as 2026 names, but no individual official product detail pages were located in this pass. They were not inserted into the canonical catalog.

Sources consulted for this follow-up include:
- Official French Avenue Prune Hypnos detail page: https://frenchavenue.com/products/prune-hypnos
- French Avenue-branded regional pages: https://french-avenue.ma/product/fleuriche-bisou-rose and https://french-avenue.ma/product/papa-yeah-extradose
- Distributor product listings: https://novaluxeurope.com/en/marcas/french-avenue/
- Secondary discovery indexes: https://www.fragrantica.com/designers/French-Avenue.html and https://basenotes.com/brands/french-avenue.26275552

The key rule remains unchanged: discovery databases may reveal candidate names, but catalog concentration and size should be entered only when the underlying product evidence supports them.


### Afnan official-page verification: 9 PM Night Out

The existing Afnan identity **9 PM Night Out** was cross-checked against Afnan's official regional product page:
- Product page: https://de.afnan.com/en/products/9pm-night-out
- Official specifications: Extrait de Parfum, 100 ml, unisex
- Official launch announcement: https://afnan.com/blogs/news/afnan-perfumes-unveils-9pm-night-out-on-the-global-stage (17 February 2026)
- Catalog action: updated `source_url`, changed evidence status to `source_verified_name`, set concentration to `Extrait de Parfum`, and added an explicit 100 ml variant.
- No new canonical identity was created; the existing Afnan row was upgraded.

Afnan now has 87 identities: 1 `source_verified_name` and 86 `source_listed_name`. The requested 20-brand subtotal remains 2,049 identities; the evidence-status subtotal is now 232 verified and 1,817 listed. The full seed remains 2,052 products and now contains 219 explicit variants.

Sources:
- https://de.afnan.com/en/products/9pm-night-out
- https://afnan.com/blogs/news/afnan-perfumes-unveils-9pm-night-out-on-the-global-stage


### Zimaya official new-launch additions

A review of Zimaya's official New Launches collection and regional brand storefronts identified five standalone perfumes absent from the existing 72-row Zimaya subset. Each has an individual Zimaya product page and explicit 100 ml EDP specification. They were added as new canonical identities with official `source_url` values and explicit 100 ml EDP variants:

| Canonical identity | Official product page | Size / concentration |
|---|---|---|
| Kibria Supremo | https://ro.zimayaperfumes.com/products/kibria-supremo | 100 ml / Eau de Parfum |
| Oscar Platinum | https://fr.zimayaperfumes.com/products/oscar-platinum | 100 ml / Eau de Parfum |
| Zukhruf Peach Please | https://de.zimayaperfumes.com/en/products/zukhruf-peach | 100 ml / Eau de Parfum |
| Mazaaj Rhythm | https://zimayaperfumes.com/products/mazaaj-rhythm | 100 ml / Eau de Parfum |
| Tiramisu S’mores | https://zimayaperfumes.com/products/tiramisu-s-mores | 100 ml / Eau de Parfum |

These are distinct perfumes, not gift sets or body-care items. Their product identities were not already present under alternate names in the Zimaya seed. Zimaya now has 77 identities: 15 `source_verified_name` and 62 `source_listed_name`.

Sources:
- Official Zimaya new launches: https://zimayaperfumes.com/collections/new-launch-1
- Official product detail pages listed in the table above.

### Afnan official-page verification: 9 PM Night Out

The existing Afnan identity **9 PM Night Out** was cross-checked against Afnan's official regional product page:
- Product page: https://de.afnan.com/en/products/9pm-night-out
- Official specifications: Extrait de Parfum, 100 ml, unisex
- Official launch announcement: https://afnan.com/blogs/news/afnan-perfumes-unveils-9pm-night-out-on-the-global-stage (17 February 2026)
- Catalog action: updated `source_url`, changed evidence status to `source_verified_name`, set concentration to `Extrait de Parfum`, and added an explicit 100 ml variant.
- No new canonical identity was created; the existing Afnan row was upgraded.

Afnan now has 87 identities: 1 `source_verified_name` and 86 `source_listed_name`. The requested 20-brand subtotal is 2,054 identities: 135 `source_verified_name` and 1,919 `source_listed_name`. The full seed contains 2,061 products and 230 explicit variants.

Sources:
- https://de.afnan.com/en/products/9pm-night-out
- https://afnan.com/blogs/news/afnan-perfumes-unveils-9pm-night-out-on-the-global-stage


## Paris Corner and Maison Alhambra official-page verification

### Paris Corner: Midnight Sin by Daniel René

The existing canonical identity **Midnight Sin by Daniel René** was matched to the official Paris Corner product page:
- https://www.pariscornerperfumes.com/products/midnight-sin-by-daniel-rene
- Official page explicitly lists size **100 ml** and the fragrance notes.
- The page does not explicitly state concentration in the extracted product specification; therefore no concentration value was invented.
- Catalog action: source URL upgraded from collection page to individual product page, evidence status changed to `source_verified_name`, and an explicit 100 ml variant was added without a concentration field.
- No duplicate canonical identity was created.

**Rifaaqat Ume** was also checked. The official Paris Corner UAE storefront's New Launches/collection listing identifies it as **85 ml**, but no individual official product detail page with a complete product specification was located in this pass. It remains a discovery lead and was not promoted to a verified canonical row or variant.

### Maison Alhambra: four new canonical identities

Four fragrances absent from the existing 203-row Maison Alhambra subset were confirmed on individual Maison Alhambra USA product pages. Each official page states Eau de Parfum and 100 ml. They were added as distinct canonical identities with official product URLs and explicit 100 ml EDP variants:

| Canonical identity | Official product page | Size / concentration |
|---|---|---|
| Minerale Gold | https://maisonalhambra-usa.com/products/maison-alhambra-minerale-gold-eau-de-parfum-for-everyone | 100 ml / Eau de Parfum |
| Victorioso Fearless | https://maisonalhambra-usa.com/products/maison-alhambra-victorioso-fearless-eau-de-parfum-for-everyone | 100 ml / Eau de Parfum |
| The Memory of Oud | https://maisonalhambra-usa.com/products/maison-alhambra-the-memory-of-oud-eau-de-parfum-for-everyone | 100 ml / Eau de Parfum |
| Sceptre Oceana | https://maisonalhambra-usa.com/products/maison-alhambra-sceptre-oceana-eau-de-parfum-for-everyone | 100 ml / Eau de Parfum |

### Maison Alhambra: existing identities upgraded

Two existing canonical identities were retained and their source URLs upgraded to individual product pages. Their official EDP/100 ml specifications are now represented by explicit variants:
- **Leonie** — https://maisonalhambra-usa.com/collections/womens-best-seller/products/maison-alhambra-leonie-eau-de-parfum-for-women
- **Leonie Intense** — https://maisonalhambra-usa.com/products/maison-alhambra-leonie-intense-eau-de-parfum-for-women

Leonie already had a matching 100 ml EDP variant, so it was retained and not duplicated. Leonie Intense received a new explicit 100 ml EDP variant.

Maison Alhambra now has 207 identities: 6 `source_verified_name` and 201 `source_listed_name`. Paris Corner remains at 245 identities, now with 7 `source_verified_name` and 238 `source_listed_name`.

Official sources:
- Paris Corner Midnight Sin: https://www.pariscornerperfumes.com/products/midnight-sin-by-daniel-rene
- Paris Corner UAE New Launches: https://ae.pariscorner.com/
- Maison Alhambra USA New In: https://maisonalhambra-usa.com/collections/new-in
- Individual Maison Alhambra product pages in the tables above.


### Al Haramain: individual official product-page verification (8 November 2026)

Eight existing canonical identities were checked against individual Al Haramain EU storefront product pages. No new canonical identities were created. The catalog rows were upgraded from `source_listed_name` to `source_verified_name`, their source URLs now point to the official product details, and explicit size/concentration variants were recorded:

| Canonical identity | Official product detail | Concentration | Verified size(s) |
|---|---|---|---:|
| Amber Oud Ruby Edition | https://shop.alharamainperfumes.com/eu/haramain-amber-oud-ruby-edition-100-ml.html | Eau de Parfum | 100 ml |
| Amber Oud Ruby Edition | https://shop.alharamainperfumes.com/eu/amber-oud-ruby-edition-120ml.html | Eau de Parfum | 120 ml |
| Amber Oud Gold Edition Extreme | https://shop.alharamainperfumes.com/eu/haramain-amber-oud-gold-edition-extreme-100ml.html | Extrait de Parfum | 100 ml |
| Azlan Oud Bleu Edition | https://shop.alharamainperfumes.com/eu/azlan-oud-bleu-edition-100ml-spray.html | Extrait de Parfum | 100 ml |
| Azlan Oud Saffron Edition | https://shop.alharamainperfumes.com/eu/haramain-azlan-oud-saffron-edition-100ml-spray.html | Extrait de Parfum | 100 ml |
| L'Aventure Grapefruit | https://shop.alharamainperfumes.com/eu/haramain-l-aventure-grapefruit-spray.html | Extrait de Parfum | 100 ml |
| L'Aventure Iris | https://shop.alharamainperfumes.com/eu/haramain-l-aventure-iris-spray.html | Extrait de Parfum | 100 ml |
| L'Aventure Ciel | https://shop.alharamainperfumes.com/eu/haramain-l-aventure-ciel-spray.html | Extrait de Parfum | 100 ml |
| Amber Oud Aqua Dubai | https://shop.alharamainperfumes.com/eu/haramain-amber-oud-gold-aqua-dubai-100ml-extrait-de-parfum.html | Extrait de Parfum | 100 ml |

Amber Oud Ruby Edition is one canonical identity with two verified sizes, not two products. Collection pages also display other sizes for some fragrances, but those sizes were not added unless supported by the inspected individual detail pages. Gift sets, deodorants, oils and other non-spray formats remain outside the canonical spray-fragrance variant model.

The requested-brand subtotal remains 2,057 identities after the previously removed Zimaya duplicate. Evidence status is now 150 individual-page verified identities and 1,907 listing-level identities. The full catalog remains 2,060 identities.


### Assaf: individual official product-page verification (8 November 2026)

Seven existing Assaf canonical identities were checked against individual product pages on the brand-owned `assaf.ae` storefront. The rows now point to their official product pages, have `source_verified_name` evidence status, and carry only the sizes explicitly shown on those pages:

| Canonical identity | Official product detail | Verified size(s) |
|---|---|---:|
| Arrogate Pink | https://assaf.ae/products/arrogate-pink-200ml | 200 ml |
| Arrogate Pink Diva | https://assaf.ae/products/arrogate-pink-diva | 200 ml |
| Dangerous Arrogate | https://assaf.ae/products/dangerous-arrogate-200ml | 200 ml |
| Gris Erik | https://assaf.ae/products/gris-erik-200-ml and https://assaf.ae/products/gris-erik | 100 ml, 200 ml |
| Miss Arrogate | https://assaf.ae/products/miss-arrogate | 200 ml |
| Rebel Enable | https://assaf.ae/products/edp-rebel-enable-150ml | 150 ml |
| Wild Colt Elixir | https://assaf.ae/products/edp-wild-colt-elixer-200ml | 200 ml |

No concentration was inferred because the inspected pages did not consistently provide an explicit concentration field for these items. The 100 ml and 200 ml Gris Erik listings remain variants of one canonical identity. Existing independent-index rows not covered by individual official pages remain listing-level.

After these updates, the Assaf subtotal remains 140 identities: 7 individually detail-verified and 133 listing-level. Across the 20 requested brands, the subtotal remains 2,057 identities: 157 `source_verified_name` and 1,900 `source_listed_name`.


### Paris Corner: eight further official product-page verifications (8 November 2026)

Eight existing Paris Corner identities were checked against individual product-detail pages on the brand's official storefront. No new canonical identities were created. Each page explicitly states a 100 ml size, so one 100 ml variant was added to each existing identity:

| Canonical identity | Official product detail | Explicit concentration |
|---|---|---|
| Dulzura Vanilla Envie | https://www.pariscornerperfumes.com/products/dulzura-vanilla-envie | Not stated on page |
| Empire de la Rouge | https://www.pariscornerperfumes.com/products/empire-de-la-rouge | Eau de Parfum |
| Green Bet | https://www.pariscornerperfumes.com/products/green-bet | Not stated on page |
| Heer | https://www.pariscornerperfumes.com/products/heer | Not stated on page |
| Marshmallow Blush | https://www.pariscornerperfumes.com/products/marshmallow-blush | Not stated on page |
| Oravea | https://www.pariscornerperfumes.com/products/oravea | Eau de Parfum |
| Rawq | https://www.pariscornerperfumes.com/products/rawq | Not stated on page |
| The Show Magnifique | https://www.pariscornerperfumes.com/products/the-show-magnifique | Not stated on page |

For the six pages that only state size, concentration was deliberately left blank in both the canonical row and variant. Ciao Citrus and Zariya remain listing-level because this pass found collection/new-launch evidence but did not verify their individual product-detail specifications. No new products were inferred from bundle listings.

Paris Corner remains at 245 canonical identities; 15 are now individually detail-verified and 230 remain listing-level. The full seed remains at 2,060 canonical identities and now has 255 explicit variants. Across the 20 requested brands, the subtotal is 2,057 identities: 165 individually verified and 1,892 listing-level.

Official source pages:
- https://www.pariscornerperfumes.com/products/dulzura-vanilla-envie
- https://www.pariscornerperfumes.com/products/empire-de-la-rouge
- https://www.pariscornerperfumes.com/products/green-bet
- https://www.pariscornerperfumes.com/products/heer
- https://www.pariscornerperfumes.com/products/marshmallow-blush
- https://www.pariscornerperfumes.com/products/oravea
- https://www.pariscornerperfumes.com/products/rawq
- https://www.pariscornerperfumes.com/products/the-show-magnifique


### Paris Corner: eleven additional official detail pages (8 November 2026)

The official Paris Corner "New Arrivals Offer" collection linked directly to individual product pages for these fragrances. Eleven existing collection-level records were upgraded to source_verified_name, and explicit variants were added. One item, Ministry of Oud - Thailand Oud in Cairo, was present in the family registry but absent from the canonical product seed; it was added as one new canonical identity.

| Canonical identity | Official product page | Size | Concentration stated |
|---|---|---:|---|
| Tawaaq | https://www.pariscornerperfumes.com/products/tawaaq | 100 ml | Not stated |
| Lueur d'Espoir Noche | https://www.pariscornerperfumes.com/products/lueur-noche | 100 ml | Not stated |
| Lueur d'Espoir Arena | https://www.pariscornerperfumes.com/products/lueur-arena | 100 ml | Eau de Parfum |
| Lueur d'Espoir Ambre | https://www.pariscornerperfumes.com/products/lueur-ambre | 100 ml | Not stated |
| North Stag Neuf IX | https://www.pariscornerperfumes.com/products/north-stag-neuf-ix | 100 ml | Extrait de Parfum |
| North Stag Sept VII | https://www.pariscornerperfumes.com/products/north-stag-sept-vii | 100 ml | Extrait de Parfum |
| Rose de Nuit | https://www.pariscornerperfumes.com/products/rose-de-nuit | 100 ml | Eau de Parfum |
| Super Crush Emir | https://www.pariscornerperfumes.com/products/super-crush-emir | 75 ml | Not stated |
| Ministry of Oud - Thailand Oud in Cairo | https://www.pariscornerperfumes.com/products/ministry-of-oud-thailand-oud-in-cairo | 100 ml | Not stated |
| Charuto Mysterious Tobacco | https://www.pariscornerperfumes.com/products/paris-corner-perfumes | 100 ml | Eau de Parfum |
| North Stag Huit VIII | https://www.pariscornerperfumes.com/products/north-stag-huit-viii | 100 ml | Extrait de Parfum |

Concentration is intentionally blank where the detail page did not state it explicitly. The 75 ml size for Super Crush Emir is retained as a distinct variant, not normalized to 100 ml. The Ministry of Oud item is treated as a Paris Corner sub-line, matching its existing family-registry entry.

Paris Corner now has 246 canonical identities: 26 individually detail-verified and 220 listing-level. The full seed now has 2,061 canonical identities and 266 explicit variants. Across the 20 requested brands, the count is 2,058 identities: 176 individually verified and 1,882 listing-level.

Official collection context: https://www.pariscornerperfumes.com/collections/new-arrivals-offer


### North Stag: six individual product-page checks (8 November 2026)

The official North Stag collection exposes nine fragrance identities plus a three-piece set. The set is not counted as a new fragrance. Six existing identities were checked against their individual product pages:

| Identity | Official product page | Size confirmed |
|---|---|---:|
| Quatre IV Expressions North Stag | https://www.pariscornerperfumes.com/products/quatre-iv-expressions-north-stag | Not stated on detail page |
| Trois III Expressions North Stag | https://www.pariscornerperfumes.com/products/trois-iii-expressions-north-stag | Not stated on detail page |
| Deux II Expressions North Stag | https://www.pariscornerperfumes.com/products/deux-ii-expressions-north-stag-100ml | 100 ml in product title |
| Un I Expressions North Stag | https://www.pariscornerperfumes.com/products/un-i-expressions-north-stag | Not stated on detail page |
| North Stag Phenomenal Quatorze XIV | https://www.pariscornerperfumes.com/products/north-stag-phenomenal-quatorze-xiv | 100 ml |
| North Stag Hypnotic Oud Quinze XV | https://www.pariscornerperfumes.com/products/north-stag-hypnotic-oud-quinze-xv | 100 ml |

The three pages without an explicit size were upgraded to individual-page identity evidence only; no size or variant was invented. Deux II, Phenomenal Quatorze and Hypnotic Oud each have one 100 ml variant. No concentration was populated from this pass because the individual pages did not clearly state one for these specific products. The collection page also lists a North Stag Set of Three; it remains excluded as a separate canonical fragrance because it is a bundle of existing perfumes.

The North Stag collection lists 10 sellable items including the three-piece set, and describes the range as nine fragrances. The catalog continues to represent the fragrance identities separately from the bundle.

After this pass Paris Corner has 246 identities: 31 individually detail-verified and 215 listing-level. The full seed has 2,061 canonical identities and 268 explicit variants. Across the 20 requested brands the subtotal is 2,058 identities: 181 individually verified and 1,877 listing-level.

Official collection: https://www.pariscornerperfumes.com/collections/north-stag-1
