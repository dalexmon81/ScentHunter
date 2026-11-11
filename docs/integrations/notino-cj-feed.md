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
- **Canonical matching result: zero exact GTIN matches are currently possible.**
  The current canonical JSON catalog has 1,389 products and 511 variants, but
  none of the variants has a GTIN recorded. Therefore the exact-GTIN adapter
  cannot promote any feed row today. The separate read-only candidate report
  ranks product and variant identities for manual review; it does not authorize
  offer import or write GTINs back to the catalog.

## Important limitation
The adapter and persistence tests do not activate production ingestion, change
search behavior, seed/activate the Notino store, or schedule downloads. Phase 2
uses an isolated SQLite database; PostgreSQL migration remains deferred.
The feed has not been imported into any database.


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
- No exact GTIN matches were possible because no canonical variant has a GTIN.
- Automatic matches: zero. Every candidate requires human verification.

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

