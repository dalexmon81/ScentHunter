# ScentHunter Offer Engine v1

Additive replacement architecture boundary. It is not mounted into production.

## Data flow
1. Independent retailer connector discovers retailer-owned listings (feed/API first; sitemap/site search second).
2. Persist listing and raw attributes. Connectors never invent canonical IDs.
3. Resolve listing to one explicit product and variant. Unresolved/ambiguous listings stay out of comparison.
4. Record immutable price/stock observations with source, timestamp, evidence URL and content hash.
5. Publish fresh, verified observations with explicit availability and canonical variant; in-stock observations also require a price, while sold-out observations are retained without a price.
6. Keep observations as history; current offers are a pointer to the latest accepted observation.

## Non-negotiable invariants
- Retailer listing is not canonical product identity.
- Variant identity includes exact size and package type; concentration is explicit.
- Request failure means unknown, never out of stock.
- Missing evidence means no publication. In-stock observations without a price are not published as purchasable offers.\n- A verified out-of-stock observation with no price remains the current availability state, so an old in-stock price cannot linger.
- Stale observations remain history, never current offers.
- One retailer failure cannot stop other connectors.
- Ambiguous matches are never auto-published.

## Execution
The `OfferEngineRunner` executes connectors independently, records each observation through the transactional repository, and reports per-retailer success/partial/failed outcomes. The `live_deloox_smoke` command exercises the real Deloox search and product pages without opening a database or writing catalog data; Run it manually from an environment allowed by Deloox; automated CI runners may receive a Cloudflare Client Challenge instead of the storefront. A retailer discovery failure or a single bad listing does not stop the remaining retailers/listings. Cross-retailer listings are rejected. The runner does not create database connections or enable production traffic.

The opt-in worker is executable with `SCENTHUNTER_OFFER_ENGINE_DSN=postgresql://... python -m backend.offer_engine.cli --query "Liquid Brun"`. Apply the isolated schema explicitly with `--apply-migration`; migrations are never run automatically. The worker opens and closes its own dedicated PostgreSQL connections and never touches the legacy SQLite catalog.

## Storage
The PostgreSQL migration creates a separate sh_* data model and does not alter legacy tables. Production cutover waits for repository/worker implementation, reviewed backfill, live connector tests and parity gates.

## First vertical slice
Implement Deloox end-to-end against this contract. Prove Liquid Brun 100 ml and Limited Edition 150 ml, including sold-out state, from live source pages; sold-out variants must remain visible without a price. Then add the next retailer. Do not enable the new API until these live tests pass.
