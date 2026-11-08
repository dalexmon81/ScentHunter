# Paris Corner product-page verification — 2026-11-08

## Official brand structure

Paris Corner's official site lists the following under its Brands menu: Paris Corner, North Stag, Pendora, Emir, Ministry of Gourmand, Ministry of Oud and Magic Oud Series. The official descriptions explicitly call North Stag, Emir, Pendora Scents and Ministry of Gourmand series/collections under Paris Corner. These are represented as collection/line metadata, not as separate perfume manufacturers.

Official sources:
- https://www.pariscornerperfumes.com/
- https://www.pariscornerperfumes.com/collections/paris-corner
- https://www.pariscornerperfumes.com/collections/emir-1
- https://www.pariscornerperfumes.com/collections/north-stag-1
- https://www.pariscornerperfumes.com/collections/pendora-scents-1
- https://www.pariscornerperfumes.com/collections/ministry-of-gourmand

## Detail-page verified identities

Six existing Paris Corner canonical identities were upgraded from collection-listed to individual product-page verified:
- Affogato Al Caffe — Paris Corner line
- Minya Caramel Dulce — Minya line
- Reham Rose Petals — Reham line
- Acadia Intenso Emir — Emir
- Attractus — Pendora Scents
- North Stag Hypnotic Oud Quinze XV — North Stag

The official detail pages state a 100 ml size for each. One explicit 100 ml variant was added for each product, each carrying the official product URL.

## Data-quality decisions

- Parent brand remains `Paris Corner`; `collection_name` records the official sub-line/series.
- No sub-line was fabricated as a new manufacturer.
- The existing 243 product identities were not bulk-renamed or bulk-reassigned from collection titles alone.
- No product identities were added from headline collection totals.
- No prices, stock, availability, retailer offers, shipping, GTINs or affiliate data were imported.
- Collection-only identities remain `source_listed_name` until an individual detail page can be verified.

## Validation

Added `backend/tests/test_paris_corner_detail_evidence.py` and included it in the catalog seed validation workflow.
