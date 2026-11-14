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
| Explicit refill/recharge variant hold | 31 | Do not map to a standard bottle; verify or create a matching refill variant |
| Ambiguous top candidate | 1,393 | A different runner-up is within 0.05 score points; compare both before mapping |
| High-confidence variant candidate | 156 | Clear score lead; still requires human identity verification |
| Medium-confidence variant candidate | 195 | Manual comparison of title, size, concentration and alternatives |
| Attribute conflict / mismatch | 100 | Hold for manual resolution |
| Low-confidence variant candidate | 210 | Manual catalog research |
| Product-only candidate | 1,290 | Product may exist, but no purchasable canonical variant is identified |
| No candidate | 5,972 | New product/brand discovery or later reprocessing |

The queue contains one best-ranked candidate and its runner-up for each feed item, with score margin, candidate IDs, product attributes, GTIN hold status, price, availability and affiliate URL. A format audit found 148 explicit refill/recharge listings; 31 already had a canonical variant candidate and are now held in a dedicated format-priority bucket. Listings described only as “rechargeable” are not treated as refill SKUs. A different runner-up within 0.05 score points is explicitly classified as ambiguous; this is a conservative ranking heuristic, not a probability. It is a prioritization aid, not a set of approved mappings.

## Safety and next gate

- Automatic matches approved: **0**.
- Canonical catalog writes: **0**.
- Production offer imports: **0**.
- Keep Notino ingestion isolated until the 156 high-priority candidates have been checked and canonical GTIN coverage has been populated/verified. The 31 explicit refill/recharge variant candidates require separate variant-format verification. The 184 invalid and 2 duplicate-GTIN rows must remain held.
- A feed refresh must rerun the XML audit and candidate generation against the current canonical catalog; this snapshot must not be treated as live price or stock data.



## Verified manual mapping — Rayhaan Aquatica 100 ml EDP (2026-11-12)

The Notino listing `RAYAQTM_AEDP10` is mapped to canonical product `SH-0066`, variant `VAR-e2cc3951b1445b9f`, using the following aligned evidence:

- Feed GTIN `6297001571330` passes the GS1 check digit.
- Feed title: `Rayhaan Aquatica Eau de Parfum pour homme 100 ml`.
- Canonical brand/name: Rayhaan / Aquatica.
- Canonical variant: Eau de Parfum, 100 ml.
- Canonical product source: [Rayhaan Aquatica official product page](https://rayhaanperfumes.com/products/rayhaan-aquatica?variant=44716035440687).
- Notino sellable product URL: `https://www.notino.fr/rayhaan/aquatica-eau-de-parfum-pour-homme/p-16407892/`.

The exact GTIN is now recorded on that one canonical variant in the PR branch catalog. This is a single-item evidence-backed mapping, not a relaxed brand/name matching rule. The candidate remains labeled `needs_human_review` in the review tooling; automatic fuzzy approvals remain disabled. Regression tests cover the real catalog GTIN mapping and replacement of the same-variant legacy Notino URL while preserving a different concentration.

No production catalog or database was changed. A disposable Phase 2 import and staging verification are still required before this mapping can be considered operationally published.
