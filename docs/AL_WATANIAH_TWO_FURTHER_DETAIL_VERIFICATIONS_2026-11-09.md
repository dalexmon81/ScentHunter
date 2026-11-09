# Al Wataniah — two further official detail-page verifications (9 November 2026)

This focused catalog update reuses two existing canonical identities and records only specifications explicitly displayed on the brand-owned individual product pages.

## Existing identities upgraded in place

- **Ameeri** — https://www.alwataniah.com/products/ameeri
  - Product detail identifies the item as Eau de Parfum.
  - Product detail explicitly states 100 ML.
  - Existing canonical product ID retained: `SH-AL-WATANIAH-AMEERI`.
  - One 100 ml Eau de Parfum variant added.

- **Sultan Al Lail** — https://www.alwataniah.com/products/sultan-al-lail
  - Product detail identifies the item as Eau de Parfum.
  - Product detail explicitly states 100 ML.
  - Existing canonical product ID retained: `SH-AL-WATANIAH-SULTAN-AL-LAIL`.
  - One 100 ml Eau de Parfum variant added.

## Data safeguards

- No new canonical identities were created.
- Existing product IDs were preserved.
- Variant IDs are deterministic and checked for collisions before insertion.
- Product source URLs and variant-level `source_evidence_url` values point to the corresponding individual official product page.
- The Al Wataniah family registry now declares the matching 100 ml formats.
- No prices, stock, offers, shipping data, GTINs or affiliate data were added.
- Attar Al Wesal was already verified and was not duplicated or modified.

The regression test is added to the existing `test_al_wataniah_detail_evidence` module, which is already included in the Catalog seed validation workflow.
