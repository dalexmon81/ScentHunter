# NOTINO.fr catalog match review snapshot — 2026-11-11

## Scope and provenance

This is a review snapshot derived from the saved NOTINO CJ feed extraction updated on 2026-11-10 and the existing full-catalog candidate output. It is **not** a fresh download or re-audit of the original XML in this run. The saved core-fragrance extract contains 9,533 product rows. Gift sets and other scented accessories were excluded from the core matching set.

The candidate output contains 22,055 ranked candidate rows for 9,533 unique Notino external product IDs. The canonical catalog snapshot used for this analysis contains 1,389 canonical products and 511 variants. None of those 511 variants currently has a GTIN.

## Findings

- 9,533 core-fragrance feed rows reviewed.
- 3,379 rows have at least one candidate in the saved matching output; 6,154 have no candidate.
- Exact GTIN matches to the canonical catalog: **0**, because the canonical variants have no GTIN values.
- Feed GTIN check-digit validation: 9,349 valid; 184 invalid.
- One duplicate GTIN group affects two distinct Notino external IDs: `5055654026123` (Missguided Babe Power 80 ml EDP). Both rows are held for duplicate resolution.
- 6,917 rows have a sale price.
- The saved feed quality audit reports explicit EUR prices, availability, affiliate URLs and timestamps for all 9,533 rows; all were marked in stock at the time of that snapshot.

## Review queue, ordered by action priority

| Priority | Rows | Treatment |
|---|---:|---|
| Invalid GTIN hold | 184 | Do not map or publish until source GTIN is corrected |
| Duplicate GTIN hold | 2 | Resolve duplicate identity before mapping |
| Ambiguous top candidate | 1,416 | A different runner-up is within 0.05 score points; compare both before mapping |
| High-confidence variant candidate | 160 | Clear score lead; still requires human identity verification |
| Medium-confidence variant candidate | 199 | Manual comparison of title, size, concentration and alternatives |
| Attribute conflict / mismatch | 98 | Hold for manual resolution |
| Low-confidence variant candidate | 211 | Manual catalog research |
| Product-only candidate | 1,291 | Product may exist, but no purchasable canonical variant is identified |
| No candidate | 5,972 | New product/brand discovery or later reprocessing |

The queue contains one best-ranked candidate and its runner-up for each feed item, with score margin, candidate IDs, product attributes, GTIN hold status, price, availability and affiliate URL. A different runner-up within 0.05 score points is explicitly classified as ambiguous; this is a conservative ranking heuristic, not a probability. It is a prioritization aid, not a set of approved mappings.

## Safety and next gate

- Automatic matches approved: **0**.
- Canonical catalog writes: **0**.
- Production offer imports: **0**.
- Keep Notino ingestion isolated until the 167 high-priority candidates have been checked and canonical GTIN coverage has been populated/verified. The 184 invalid and 2 duplicate-GTIN rows must remain held.
- A feed refresh must rerun the XML audit and candidate generation against the current canonical catalog; this snapshot must not be treated as live price or stock data.

