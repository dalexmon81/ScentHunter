# Mykonos catalog completeness audit — 2026-11-08

## Result

The Mykonos seed on this branch contains **98 canonical product identities and 83 explicit variants**.

The authorized EU retailer's current A–Z index lists 101 named items. Its list includes 12 products explicitly labelled *Fragrance Mist*, which are body mists rather than perfume products and are intentionally not imported into the perfume catalog. The remaining **89 perfume identities are all present** in ScentHunter.

The catalog also retains nine identities beyond the current 89-name EU A–Z list: eight legacy/historical fragrance names listed by Fragrantica (Adelina, Bloody Mary, Crystals, Eclipse, Nashi Pear Garden, Roulette, Zeus and It's Not Ella), plus Soft Hour x NCT Haechan, which is listed by the EU retailer's new-release explorer but is not yet in its current A–Z list. The eight legacy entries remain source_listed_name and have no guessed size or concentration variants. Soft Hour has a separately documented 100 ml Extrait de Parfum listing. None of these entries is treated as confirmation of current stock.

## Matching and naming rules

Known spelling / display-name differences resolve to existing canonical identities rather than creating duplicates:
- Jinx → Jynx
- Nautilius → Nautilus
- Empire → Empire x RRQ
- California Signature → California
- XoXo, Rosy → Xoxo Rosy
- Shades Parfum → Shades Perfume
- Intimate Affair → Affair

The California Signature product page itself identifies the product as California, so this is a display-name alias, not a separate fragrance.

## Validation

- 98 Mykonos products in product_catalog.json.
- 98 Mykonos identities in family_registry.json.
- 83 Mykonos variants.
- No duplicate product IDs.
- No duplicate variant IDs.
- No orphan variants.
- Every Mykonos identity has a source URL and identity status.
- Regression test asserts all 89 current EU A–Z perfume identities are present and the 12 body mists are excluded.
- Legacy entries are checked to ensure no unsupported variants are inferred.

## Sources reviewed

- Fragrantica designer index: https://www.fragrantica.com/designers/Mykonos.html
- Authorized EU retailer, all perfumes / A–Z index: https://officialmykonos.de/collections/all-perfumes
- Authorized EU retailer, new releases: https://officialmykonos.de/collections/new-releases
- Official Indonesian Mykonos store, product catalog: https://officialmykonos.com/collections/all
- Official California product page (display name California Signature): https://officialmykonos.com/products/mykonos-california-signature-50ml

## Scope note

The 84 count on Fragrantica is a database count, not a complete or stable count of every current, announced and historical Mykonos perfume. For catalog completeness, this audit uses the authorized EU retailer's named perfume index as the current range reference, checks the Fragrantica index for additional/historical names and uses official Mykonos product pages for sizes and concentrations. Upcoming names without confirmed bottle details are kept without fabricated variants.
