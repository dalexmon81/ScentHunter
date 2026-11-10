# NOTINO.fr CJ feed integration

## Source and scope
- Source: CJ Affiliate Shopping XML export for NOTINO.fr.
- The feed is delivered by CJ HTTP and is processed as an offline file.
- This connector does not scrape Notino and is never called from a user search request.
- Only Google product category 479 (perfumes and eau de cologne) is admitted.

## Normalized fields
The adapter emits store, external ID, title, brand, GTIN, price/currency,
optional sale price, availability, affiliate URL, image, size, gender,
product type, description, feed timestamp and item group ID.

## Import safety
1. Preserve the original CJ XML export as a source artifact outside the public web root.
2. Stream entries; do not load the complete XML document into memory.
3. Validate GTIN, positive price, ISO currency, availability and affiliate URL.
4. Match exact GTIN first, then review size/concentration/brand before attaching
   an offer to a canonical variant.
5. Quarantine ambiguous matches and duplicate GTIN collisions; never merge
   products solely because titles look similar.
6. Upsert offers by (store, external_id), retaining price history and feed timestamp.
7. Do not overwrite a newer offer observation with an older feed timestamp.
8. Keep the affiliate URL as the outbound purchase URL; do not treat it as a
   canonical product URL.

## Feed snapshot analyzed on 2026-11-10
- 78,897 total feed entries.
- 9,854 entries in the perfume category.
- 9,854 perfume entries with GTIN, price, availability and affiliate URL.
- 7,145 perfume entries with a sale price.
- One duplicate GTIN collision among perfume entries, to be reviewed.
- The feed reported every perfume as in stock; availability must still be
  refreshed from subsequent feed exports.

## Important limitation
This change adds the isolated XML adapter and tests only. It does not activate
production ingestion, change search behavior, create database records, or
schedule downloads. Those steps require wiring to the repository's existing
persistence and worker interfaces after inspecting their current contracts.
