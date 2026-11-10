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

## Read-only feed audit
After extracting the XML file from the CJ ZIP, run:

```bash
python -m backend.scripts.audit_notino_cj_feed /path/to/NOTINO_fr-NotinoFR_google_all-shopping.xml --output /tmp/notino-feed-audit.json
```

The utility streams the feed and reports category counts, GTIN length buckets,
missing fields, duplicate GTIN groups, invalid identifiers and brand counts.
It does not import data or connect to the database. **Accepted GTIN length is
only a format check**; the audit does not validate check digits or prove that
an identifier belongs to the listed product.

## Review-only candidate generation

After extracting the CJ XML and obtaining the current canonical JSON catalog,
run:

```bash
python -m backend.scripts.build_notino_match_candidates \
  /path/to/NOTINO_fr-NotinoFR_google_all-shopping.xml \
  backend/product_catalog.json \
  --output /tmp/notino-match-candidates.csv
```

The CSV ranks up to five candidate variants per retailer row using:
- exact normalized brand as a mandatory gate;
- perfume name similarity across canonical names and aliases;
- size agreement when both sides provide a size;
- concentration agreement when both sides provide a concentration.

Rows are labeled `review_high`, `review_medium`, `review_low` or
`no_candidate`. These are **review priorities, not automatic match approvals**.
Known size, concentration or gender conflicts are downgraded. Missing evidence is not treated as agreement. These labels are review priorities only, not match probabilities. The tool deliberately
does not auto-accept any candidate and does not modify catalog, database,
offers or GTINs. A reviewer must verify the actual product and variant before
a GTIN or offer can be attached.

## Import safety
1. Preserve the original CJ XML export as a source artifact outside the public web root.
2. Stream entries; do not load the complete XML document into memory.
3. Validate GTIN, positive price, ISO currency, availability and affiliate URL.
4. Match exact GTIN only when the canonical catalog contains exactly one
   variant for that GTIN. Ambiguous or absent GTIN matches remain staged.
5. Do not invent canonical products or variants from retailer listings.
   Brand/name/size matching is a separate candidate-generation and review step. The review-only candidate generator is documented below; it never writes matches back to the catalog.
6. Quarantine duplicate GTIN collisions; never merge products solely because
   titles look similar.
7. Upsert offers by (store, external_id), retaining price history and feed timestamp.
8. Do not overwrite a newer offer observation with an older feed timestamp.
9. Keep the affiliate URL as the outbound purchase URL; do not treat it as a
   canonical product URL.

## Feed snapshot analyzed on 2026-11-10
- 78,897 total feed entries.
- 9,854 entries in the perfume category.
- All 9,854 perfume entries contain a GTIN, price, availability and affiliate URL.
- 9,693 perfume entries have GTIN strings with accepted lengths (8, 12, 13 or 14 digits).
- 161 entries have 10- or 11-digit identifiers and are rejected by the current
  strict GTIN validator pending source-data clarification; do not pad or rewrite them.
- 7,145 perfume entries have a sale price.
- One GTIN, 5055654026123, occurs on two distinct Missguided Babe Power feed
  IDs. Keep both source rows visible for review; do not assume they are duplicates
  that can safely be collapsed.
- All 9,854 perfume rows reported "in stock" in this snapshot.
- **Canonical matching result: zero exact GTIN matches are currently possible.**
  The current canonical JSON catalog has 1,389 products and 511 variants, but
  none of the 511 variants has a GTIN recorded. Therefore the Notino adapter
  must stage these records as pending until the canonical catalog is enriched
  with verified GTINs or reviewed name/brand/size matching is implemented.

## Important limitation
The adapter and persistence tests do not activate production ingestion, change
search behavior, seed/activate the Notino store, or schedule downloads. Phase 2
uses an isolated SQLite database; PostgreSQL migration remains deferred.
The feed has not been imported into any database.


## Packaging size normalization
- Candidate review parses millilitre values and explicit US fluid-ounce values (`fl oz`, `fl. oz.`, `fluid ounce`) and converts fluid ounces to millilitres before comparing variant sizes.
- Bare `oz` is not treated as a volume unit because it may represent weight.
- Size parsing improves candidate prioritization only. It does not approve a product match or trigger an offer import.
