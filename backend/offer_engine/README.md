# ScentHunter Offer Engine v1

Additive replacement architecture boundary. It remains disabled in production by default.

## Data flow
1. An independent retailer connector discovers retailer-owned listings (feed/API first; sitemap/site search second).
2. Persist the listing and raw attributes. Connectors never invent canonical IDs.
3. Resolve each listing to one explicit product and variant. Unresolved or ambiguous listings stay out of comparison.
4. Record immutable price/stock observations with source, timestamp, evidence URL and content hash.
5. Publish fresh, verified observations with explicit availability and canonical variant. In-stock observations also require a price; sold-out observations are retained without a price.
6. Keep observations as history; current offers point to the latest accepted observation.

## Non-negotiable invariants
- A retailer listing is not a canonical product identity.
- Variant identity includes exact size and package type; concentration is explicit.
- Request failure means unknown, never out of stock.
- Missing evidence means no publication. In-stock observations without a price are not published as purchasable offers.
- A verified out-of-stock observation with no price remains the current availability state, so an old in-stock price cannot linger.
- Stale observations remain history, never current offers.
- One retailer failure cannot stop other connectors.
- Ambiguous matches are never auto-published.
- Out-of-stock observations cannot carry a price; PostgreSQL enforces this invariant too.

## Execution
The `OfferEngineRunner` executes connectors independently, records each observation through the transactional repository, and reports per-retailer success/partial/failed outcomes. It does not create database connections or enable production traffic. A retailer discovery failure or a single bad listing does not stop the remaining retailers/listings. Cross-retailer listings are rejected.

The opt-in worker is executable with `SCENTHUNTER_OFFER_ENGINE_DSN=postgresql://... python -m backend.offer_engine.cli --query "Liquid Brun"`. Apply the isolated schema explicitly with `--apply-migration`; migrations are never run automatically. The worker opens and closes its own dedicated PostgreSQL connections and never touches the legacy SQLite catalog. When `NOTINO_CJ_FEED_URL`, `NOTINO_CJ_FEED_USERNAME` and `NOTINO_CJ_FEED_PASSWORD` are configured, the worker also reads the authorized Notino.fr CJ/VIV XML feed; the connector preserves each GTIN/size as a separate listing, and the feed row is still passed through canonical identity resolution before publication. The listing schema permits multiple variant-specific external IDs to share one parent product URL.

The read-only API mounts only when `SCENTHUNTER_OFFER_ENGINE_API_ENABLED=1` and `SCENTHUNTER_OFFER_ENGINE_DSN` is configured. It exposes `GET /offer-engine/search?query=Liquid+Brun&market=BE`. The current-state read model includes sold-out variants with `availability=out_of_stock` and `price=null`, and excludes states older than each retailer’s `max_offer_age_seconds`. It does not replace the legacy `/search` endpoint yet.

The `live_deloox_smoke` command exercises the real Deloox search and product pages without opening a database or writing catalog data. Run it manually from an environment allowed by Deloox; automated CI runners may receive a Cloudflare Client Challenge instead of the storefront.

## Storage and cutover
The PostgreSQL migration creates a separate `sh_*` data model and does not alter legacy tables. Production cutover waits for dedicated PostgreSQL provisioning, read API/application integration, reviewed backfill, live connector tests and parity gates.

## First vertical slice
- Deloox uses the existing parser through a browser-aware search/product-page connector. Its live source smoke test must prove Liquid Brun 100 ml and Limited Edition 150 ml, including the sold-out state, before cutover.
- Notino uses the authorized CJ/VIV XML feed when credentials are configured. Feed variants remain separate by size/GTIN and pass through the same canonical resolver and publication policy.
- Then add the remaining retailers one at a time with their own source-specific tests. Do not enable the new API until live Deloox validation, Notino feed validation, backfill and parity gates pass.
