# NOTINO.fr CJ feed integration

## Isolated staging: retailer-only feed search

The staging import additionally keeps a complete, atomically replaced snapshot
of valid, in-stock/out-of-stock CJ listings. Price, source timestamp and the
original CJ click URL are retained; malformed links, timestamps and non-fragrance
rows are rejected and counted. An older observation for an existing listing
rejects the snapshot instead of overwriting newer data.

With `NOTINO_CJ_STANDALONE_ENABLED=1` on isolated staging, an unmatched
listing can be displayed as a **Notino-only** result. It is not a canonical
identity or a cross-retailer match. Exact-GTIN offers remain preferred, and
standalone listings are excluded when that same listing is already returned
as an exact match. Prices are labeled old after 24 hours from the earlier of
the feed's source update and the import; re-importing an old file cannot make
its prices appear fresh. When the snapshot table exists, canonical Notino
offers also use its validated current price and CJ URL, and disappear if their
listing is absent, unavailable, or no longer has the same GTIN.
The switch defaults off outside staging. Normalized brand-plus-product queries
work across the two fields without accepting SQL wildcard input.

The 2026-11-11 CJ review snapshot also supplied 14 unique Hawas 100 ml EDP
GTINs with exact catalog brand/name agreement. Eleven previously missing
variants and three existing variants are annotated in the catalog metadata.
These are retailer-feed observations, not independent manufacturer verification.

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

The CSV ranks up to five candidates per core-fragrance retailer row using:
- exact normalized brand as a mandatory gate (except exact GTIN evidence);
- perfume name similarity across canonical names and aliases;
- size agreement when both sides provide a size;
- concentration agreement when both sides provide a concentration.

The generator indexes all canonical products, not only products with variants.
Products without a variant appear as `product_only` candidates with an empty
variant ID and no size/GTIN evidence. They may identify a possible fragrance
family, but cannot identify a purchasable variant. The candidate run includes
only terminal product types `Toaletní vody`, `Parfémované vody`,
`Kolínské vody`, `Parfémy`, `Parfémované oleje` and `Eau Fraîche`;
gift sets and accessories are excluded.

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
- 9,533 core fragrance listings after excluding gift sets and accessories.
- 9,349 rows have a GTIN that passes the GTIN-8/12/13/14 GS1 check-digit
  validator; 184 fail format or checksum validation and must remain pending.
  Never pad or repair an identifier automatically.
- The core subset contains 2,049 Toaletní vody, 6,222 Parfémované vody,
  172 Kolínské vody, 914 Parfémy, 148 Parfémované oleje and 28 Eau Fraîche.
- One GTIN, 5055654026123, occurs on two distinct Missguided Babe Power feed
  IDs. Keep both source rows visible for review; do not assume they are duplicates
  that can safely be collapsed.
- The 9,533 core fragrance rows were analyzed separately from the broader Google category 479 feed population.
- **Historical snapshot result (2026-11-10): zero exact GTIN matches were possible.**
  At that time the canonical JSON catalog had 1,389 products and 511 variants,
  with no GTIN recorded on variants. The subsequent enrichment is documented
  in the dated update below. Candidate scores remain ranking evidence, not
  independent human identity approval.

## Important limitation
The adapter and persistence tests do not activate production ingestion, change
production ingestion, seed/activate the Notino store, or schedule production
downloads. PR #726 has a separate, explicitly isolated staging workflow for
Phase 2. The feed is never imported into the production database; PostgreSQL
migration remains deferred.


## Packaging size normalization
- Candidate review parses millilitre values and explicit US fluid-ounce values (`fl oz`, `fl. oz.`, `fluid ounce`) and converts fluid ounces to millilitres before comparing variant sizes.
- Bare `oz` is not treated as a volume unit because it may represent weight.
- Size parsing improves candidate prioritization only. It does not approve a product match or trigger an offer import.

## Refined core-catalog comparison (2026-11-10)

The uploaded CJ XML was compared against the exact branch catalog blob
(Git blob SHA `23ee4a7b026148f666e729bec63cf1af25c2ee29`). The comparison
indexed all 1,389 canonical products: 511 variant records plus 1,063
product-only identities for products without a variant.

Results for the 9,533 core fragrance feed rows:
- 3,379 rows received at least one brand/name candidate; 6,154 received none.
- 167 top-ranked candidates fell into the strongest existing-variant score band before comparing the runner-up; the reproducible priority queue now splits these into 160 with a clear lead and 7 ambiguous alternatives.
- 1,017 rows were ambiguous; 292 medium-priority; 1,585 low-priority;
  318 were downgraded for known size, concentration or gender conflicts.
- No exact GTIN matches were possible in the 2026-11-10 catalog snapshot because no canonical variant then had a GTIN.
- Automatic matches: zero. Every candidate required human verification.

These are candidate-ranking statistics, not confirmed match counts. A row with
no candidate is not proof that the fragrance is new: missing aliases, retailer
brand labels, incomplete product records and absent variants can all prevent
a match. Product-only candidates identify a possible fragrance family but do
not identify a purchasable variant.


## Canonical brand coverage audit

To separate brands genuinely absent from the canonical catalog from brands
already represented but missing product names, aliases or variants, run:

```bash
python -m backend.scripts.audit_notino_catalog_coverage \
  /path/to/NOTINO_fr-NotinoFR_google_all-shopping.xml \
  backend/product_catalog.json \
  --candidates /tmp/notino-match-candidates.csv \
  --csv /tmp/notino-brand-coverage.csv \
  --json /tmp/notino-brand-coverage.json
```

The report is read-only. It groups core feed rows by normalized brand, reports
whether a canonical brand exists, valid/invalid GTIN counts and candidate
coverage when a candidate CSV is supplied. A brand present in the catalog but
with no candidate is classified as a name/alias/variant gap, not as a new
brand. A brand absent from the catalog is a catalog expansion candidate only;
it is not an instruction to import every retailer listing.


## Notino catalog-expansion review queue (read-only)

Generate a proposal queue for feed brands not yet represented in the canonical
catalog:

```bash
python -m backend.scripts.build_notino_catalog_expansion_review \
  /path/to/NOTINO_fr-NotinoFR_google_all-shopping.xml \
  backend/product_catalog.json \
  --csv /tmp/notino-catalog-expansion-review.csv \
  --json /tmp/notino-catalog-expansion-review.json
```

Each retailer row is preserved. The queue includes the source title, a name
normalization candidate, parsed size/concentration/gender hints, GTIN validity,
duplicate-GTIN count, price, availability, affiliate URL and source timestamp.
Rows with invalid GTINs or a GTIN collision are held. A unique valid GTIN is
only eligible for manual identity review; it is not a canonical approval.
The script never writes the catalog or database and does not create variants.

Exact GTIN evidence in the general candidate ranker is now accepted only when
the feed and catalog identifiers both pass the GS1 check-digit validator.


## Publisher acceptance and feed authorization (2026-11-10)

VIVnetworks confirmed by email on 2026-11-10 that ScentHunter was accepted
into the NOTINO.fr affiliate program and that the feed is enabled automatically
after acceptance; no additional feed-access approval is required. VIVnetworks
also previously confirmed that price-comparison platforms are generally
permitted, with acceptance into the program decided by Notino. Continue to
follow the CJ/Notino publisher terms and the supplied Publisher & Developer
Welcome Kit for display, attribution, refresh and link requirements.

This confirms affiliate-program acceptance and feed access. It does **not**
approve any product-to-canonical mapping or allow unvalidated rows to be
published. Feed access, catalog identity validation and offer publication are
separate gates.

## Reproducible review-priority queue

After producing the core-fragrance CSV and candidate CSV, generate one
best-ranked candidate per feed external ID, retain the runner-up and score
margin, and apply GTIN holds:

```bash
python -m backend.scripts.build_notino_review_priority \
  /path/to/notino_fr_core_fragrances.csv \
  /path/to/notino-match-candidates.csv \
  --csv /tmp/notino-catalog-review-priority.csv \
  --json /tmp/notino-catalog-review-priority.json
```

The queue prioritizes invalid GTINs and duplicate feed GTINs as hard holds,
then high/medium/low variant candidates, product-only candidates and rows with
no candidate. It never approves a match and never writes to the canonical
catalog or offer database. The 2026-11-11 saved review snapshot contains
9,533 rows: 184 invalid-GTIN holds, 2 duplicate-GTIN holds, 167 high-confidence
variant candidates for human verification, 292 medium candidates, 219
attribute-conflict candidates, 400 low-confidence variant candidates, 2,297
product-only candidates and 5,972 with no candidate.

The generated queue is a review artifact based on the saved 2026-11-10 feed
extract. Re-download and audit the current CJ XML before treating any price,
availability or timestamp as current.


The review-priority builder also compares the best candidate with the runner-up.
When the runner-up is a different canonical identity and the score gap is below
0.05, the feed row is placed in an explicit ambiguous queue rather than being
labelled high confidence. This threshold is a conservative ranking heuristic,
not a probability. The 2026-11-11 queue therefore contains 1,414 ambiguous
rows across variant and product-only candidates; no candidate is auto-approved.


## Secure CJ HTTP/S export download

The Notino CJ export subscription is `324587` for publisher CID `8115142`.
VIVnetworks documents the CJ HTTP/S URL format and confirms that the HTTP
username/password are delivered separately by `datatransfer@cj.com`. The
download utility uses HTTP Basic Authentication headers; it never puts the
password in the URL or prints/stores credentials.

Set these environment variables from the CJ HTTP Server Information email:

```bash
export CJ_HTTP_USERNAME=8115142
export CJ_HTTP_PASSWORD='(use the password from the CJ email; do not commit it)'
python -m backend.scripts.download_notino_cj_feed \
  --output-dir /data/feeds/notino
```

The utility downloads the ZIP over HTTPS, checks the ZIP integrity, requires
exactly one XML member, rejects unsafe archive paths and atomically writes the
XML file. It does not import data into the catalog or offers database.

Then run the audit and review tools against the downloaded XML. For a daily
production refresh, store the two credentials as deployment secrets and invoke
the downloader from a scheduled background worker. No CJ credentials belong
in GitHub source, logs, or the public frontend.


## End-to-end read-only feed review

After downloading the XML, the complete review-only pipeline is:

```bash
XML=/data/feeds/notino/NOTINO_fr-NotinoFR_google_all-shopping.xml

python -m backend.scripts.audit_notino_cj_feed \
  "$XML" --output /tmp/notino-feed-audit.json

python -m backend.scripts.export_notino_core_feed_csv \
  "$XML" --csv /tmp/notino-core-fragrances.csv \
  --json /tmp/notino-core-fragrances.json

python -m backend.scripts.build_notino_match_candidates \
  "$XML" backend/product_catalog.json \
  --output /tmp/notino-match-candidates.csv

python -m backend.scripts.build_notino_review_priority \
  /tmp/notino-core-fragrances.csv /tmp/notino-match-candidates.csv \
  --csv /tmp/notino-catalog-review-priority.csv \
  --json /tmp/notino-catalog-review-priority.json
```

The chain audits the XML, exports the core fragrance rows with GTIN validity
and duplicate flags, generates up to five candidate rows per feed item, then
reduces them to a single prioritized review row with runner-up and ambiguity
information. All steps are offline/read-only after download; they do not
promote offers or write catalog/database records.

## GitHub Actions review workflow

The repository workflow `.github/workflows/notino-feed-review.yml` can download the
authorized CJ XML and rebuild the complete read-only review package on demand.
It runs on manual dispatch, and its initial branch-file commit also triggers one
bootstrap run. Before it can download, configure these repository Actions
secrets under **Settings → Secrets and variables → Actions**:

- `CJ_HTTP_USERNAME`: the HTTP username supplied by CJ for the data-transfer
  subscription (normally the publisher CID shown in the CJ setup email).
- `CJ_HTTP_PASSWORD`: the separate CJ HTTP/S password supplied by
  `datatransfer@cj.com`.

Do not paste either value into source files, workflow inputs, issues, or logs.
The workflow checks that both secrets exist without printing their values. If
either is absent, it stops before making a network request.

When configured, the workflow downloads the ZIP/XML into the ephemeral GitHub
runner, then rebuilds the feed audit, core-fragrance CSV, match candidates,
prioritized review queue, brand-coverage report and catalog-expansion review.
It uploads only these review outputs as a seven-day Actions artifact; the raw
XML and credentials are excluded. The workflow has no database credentials and
does not write to the catalog, Phase 2 database, production offers or store
activation state.

Open **Actions → Notino authorized feed review → Run workflow** to refresh the
review package after the secrets are configured. Every generated candidate
remains human-review-only; a successful download or audit is not an approval
to map products or publish offers.



## Canonical GTIN enrichment (2026-11-11)

The PR branch catalog was enriched with 83 GTINs across 83 existing canonical
variants using exact candidate, name, size and concentration evidence. The
Notino CJ feed additionally identifies Liquid Brun EDP 100 ml as GTIN
`6290360375694`; this valid, unique GTIN is now attached to `SH-0030` /
`VAR-f87146c82d167f4c`. It remains separate from the 150 ml Limited Edition
variant, which has GTIN `6298042001831`. The PR branch now has 84 valid,
unique GTINs across 84 existing variants. These are high-evidence identity
mappings, not independent human confirmations.

The committed catalog was re-read and checked: 511 variants, 84 GTIN values,
84 unique GTIN values and no orphan variant references. The mapping is on the
PR branch only. The Notino Phase 2 adapter can now resolve those exact GTINs
when run against a database seeded from this enriched catalog; all remaining
feed rows continue to stage for review until a unique canonical GTIN exists.

## PR #726 isolated persistent staging import

The workflow `.github/workflows/notino-phase2-staging-import.yml` writes only
to `/data/notino-phase2/catalog.sqlite3` on `scenthunter-pr726-staging`. It
deploys the current branch before importing and verifies the importer script
hash on every Fly machine. Since each Fly machine has a separate persistent
volume, it copies the snapshot and imports/verifies the database on every
machine, not just the first one.

The workflow reuses a snapshot only when its checksum is verified on every
volume; otherwise it downloads and transfers a fresh authorized CJ snapshot.
Unmatched feed rows are bulk-staged, while exact unique GTIN matches use the
normal validation and offer-promotion path. The workflow re-imports the same
snapshot and requires a stable offer count, new price-history observations,
valid canonical variant links and no duplicate retailer offer IDs. It then
restarts each staging machine and rechecks the persistent database.

Staging search reads the Phase 2 database in read-only mode. The isolated
Fly configuration disables Notino's live search fallback, so `/search` and
the frontend's `/search-start` path cannot scrape Notino when an imported
catalog offer is available (or when the catalog has no match). This setting
does not change production configuration.
