# ScentHunter Offer Engine v1

Additive replacement architecture boundary. It remains disabled in production by default.

## Data flow
1. An independent retailer connector discovers retailer-owned listings (authorized feed/API first; sitemap/site search second).
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
- Out-of-stock observations cannot carry a price; both supported database schemas enforce this invariant.

## Execution
The `OfferEngineRunner` executes connectors independently, records each observation through the transactional repository, and reports per-retailer success/partial/failed outcomes. It does not create database connections or enable production traffic. A retailer discovery failure or a single bad listing does not stop the remaining retailers/listings. Cross-retailer listings are rejected.

On Fly, the worker uses the dedicated SQLite file `/data/offer_engine.sqlite3` on the existing persistent volume. Locally, the default is a sibling `offer_engine.sqlite3` next to `SCENTHUNTER_CATALOG_DB`. Run `python -m backend.offer_engine.cli --apply-migration --query "Liquid Brun"` to create the isolated schema and execute one query. On Fly, the same migration can be applied at startup only by explicitly setting `SCENTHUNTER_OFFER_ENGINE_AUTO_MIGRATE=1`; the default is `0`. Migrations are never run automatically by default. If `SCENTHUNTER_OFFER_ENGINE_DSN` is configured, the worker instead uses the separate PostgreSQL schema and migration.

The runtime registers Deloox plus the existing parsed-search connectors for Bplatz, Easycosmetic, Orioudh, ParfumCity, ParfumZentrum, PerfumeMarket and Sabina. It adds the Notino authorized CJ/VIV XML feed connector only when `NOTINO_CJ_FEED_URL`, `NOTINO_CJ_FEED_USERNAME` and `NOTINO_CJ_FEED_PASSWORD` are configured. Notino feed variants sharing one product URL remain separate listings by size/GTIN. Every connector uses the same canonical resolver and publication policy; one retailer failure does not stop the others.

The API mounts only when `SCENTHUNTER_OFFER_ENGINE_API_ENABLED=1`. `GET /offer-engine/search?query=Liquid+Brun&market=BE` reads the dedicated current-state model; `POST` to the same path runs the configured connectors for that query, persists observations, then returns the current state. Sold-out variants are returned with `availability=out_of_stock` and `price=null`; states older than each retailer’s `max_offer_age_seconds` are excluded. The existing `/search` endpoint can be switched to this engine with `SCENTHUNTER_OFFER_ENGINE_SEARCH_ENABLED=1`; that flag is explicitly set to `0` in Fly config until cutover validation is complete.

The `python -m backend.offer_engine.live_deloox_smoke` command exercises the real Deloox search and product pages without opening a database or writing catalog data. Run it manually from an environment allowed by Deloox; automated CI runners may receive a Cloudflare Client Challenge instead of the storefront.

## Storage and cutover
The SQLite migration creates a separate `sh_*` data model in its own file on the Fly volume; it does not alter the legacy catalog database. A separate PostgreSQL database is also supported when `SCENTHUNTER_OFFER_ENGINE_DSN` is configured. Production cutover waits for live connector validation, read API/application integration, reviewed backfill and parity gates.

## First vertical slice
- Deloox uses the existing parser through a browser-aware search/product-page connector. Its live source smoke test must prove Liquid Brun 100 ml and Limited Edition 150 ml, including the sold-out state, before cutover.
- Notino uses the authorized CJ/VIV XML feed when credentials are configured. Feed variants remain separate by size/GTIN and pass through the same canonical resolver and publication policy.
- The initial registry covers Deloox, Notino (when feed credentials are configured), Bplatz, Easycosmetic, Orioudh, ParfumCity, ParfumZentrum, PerfumeMarket and Sabina. Add any remaining retailers one at a time with source-specific tests; do not enable the new API until live connector validation, feed validation, backfill and parity gates pass.
