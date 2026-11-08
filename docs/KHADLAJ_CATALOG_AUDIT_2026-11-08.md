# Khadlaj catalog audit — 2026-11-08

## Snapshot

This rebased draft contains **210 canonical Khadlaj identities and 199 explicit variants**. Every variant row has a `source_evidence_url`; no variant uses Fragrantica as proof of size or concentration.

The catalog separates the main Khadlaj spray range, concentrated perfume oils, Shiyaaka and La Fede. It preserves the existing 116 Khadlaj identities on the current catalog base and adds reconciled identities and variants from the prior catalog branches plus visible official-store products.

## Official range reconciliation

| Official store collection | Current collection count | Visible products reconciled in this draft | Remaining |
|---|---:|---:|---:|
| Perfume Sprays | 101 | 96 | 5 not exposed in the current page extraction |
| Concentrated Perfume Oils | 43 | 36 | 7 not exposed / not yet reconciled |
| La Fede Eau de Parfum | 42 | 36 | 6 not exposed / not yet reconciled |

The collection counts are a snapshot of the official store, not a statement about stock. Hidden or unexposed collection entries are not guessed into the catalog.

## What was reconciled

- The broad cross-source catalog branch contributes 166 Khadlaj identities, including the 147-name Fragrantica reconciliation and the existing Shiyaaka / La Fede records.
- The official spray audit adds the separately named **Private Blend Tobac Extra** product and 77 additional variant keys with collection-card evidence.
- The official variants branch contributes nine further supported variants not present in the spray audit. The generic `Private Blend` row is not given the Tobac Extra variant.
- Nine missing, visible oil identities were added: Johayna Purple, Kayaan Silver, Malika Green, Mukhalath Ma'a Ward Taiba, Rimaal Green, Haneen Rose Gold, Roohi Wa Roohak Silver, Zainab and Mibraak.
- Thirty-four additional La Fede products and their visible bottle variants were added from the official La Fede collection pages. The existing Intoxicate Mystique and Code Viola Nectar records were reused rather than duplicated.
- Code Viola Nectar is now assigned to the La Fede family. Celebrity Crush and Celebrity Fame remain separate La Fede products already present in the catalog.

## Variant evidence and conservative decisions

- All 199 variants now carry a variant-level evidence URL. Evidence may be an official product page or an official collection page where the exact product card identifies the size and concentration.
- **Hareem Al Sultan Gold** is represented as a 35 ml Perfume Oil, not as a spray.
- **Alf Wardaat** is retained as 30 ml: the official product page title identifies 30 ml even though the URL slug contains “25ml”.
- **Rasayel Vid** remains 100 ml Eau de Parfum, matching the official page's product title.
- **Saqr Al Badiya** remains 100 ml with concentration unspecified. The official product page title and description conflict on Extrait vs Eau de Parfum, so the concentration is deliberately not inferred.
- **Private Blend Tobac Extra** is a separate 100 ml Extrait product. Its product page is not attached to the generic Private Blend identity.
- **Musk Pure Musk Blend Creation of Iqbal** is retained as an alias of Musk Pure Musk Blend, not a second canonical fragrance.
- Opulence Bleu uses a retailer product page for its 100 ml EDP evidence; Rose & Romance uses the official product page. Neither relies on Fragrantica for variant data.

## Remaining work — do not call Khadlaj globally complete yet

1. Reconcile the five spray collection entries not exposed by the current extraction.
2. Reconcile the seven remaining perfume-oil collection entries.
3. Reconcile the six remaining La Fede collection entries.
4. The family registry still carries three legacy La Fede names (Lavish Blush, Lavish Luna and Lavish Rouge) without a verified product-page record. Keep them as family-level leads until direct evidence is found.
5. Recheck the current official store collections before finalizing the brand snapshot.

## Sources

- Official perfume sprays: https://khadlaj-perfumes.com/collections/perfumes-spray
- Official concentrated perfume oils: https://khadlaj-perfumes.com/collections/concentrated-perfume-oils
- Official La Fede EDP: https://khadlaj-perfumes.com/collections/la-fede-eau-de-parfume
- Official Private Blend Tobac Extra: https://khadlaj-perfumes.com/collections/khadlaj-na-best-sellers/products/private-blend-tobac-extra-extrait-de-parfum-100-ml-for-men
- Official Hareem Al Sultan Gold oil: https://khadlaj-perfumes.com/products/hareem-al-sultan-gold-35ml
- Official Rose & Romance: https://khadlaj-perfumes.com/collections/discover-more/products/rose-and-romance-spray-shop-online-best-price-in-dubai-uae
- Opulence Bleu retailer listing: https://www.riah.ae/en/product/ra-73550/opulence-bleu-eau-de-parfum-women-and-men-khadlaj-perfumes
- Fragrantica designer index: https://www.fragrantica.com/designers/Khadlaj.html

## Validation

Structural checks before CI: 210 Khadlaj product IDs unique; 199 variant IDs unique; no orphan variants; 199/199 variants have evidence URLs; 210 identities and 199 variants retained on top of the Mykonos-rebased catalog base.

This PR remains a draft pending CI and reconciliation of the remaining official collection entries.
