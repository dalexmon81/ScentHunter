# Review of the Perplexity architecture proposal

## Decision

**Accept the core direction. Do not copy the proposed infrastructure stack wholesale.**

The proposal correctly identifies the central product requirement: user search should query an internal canonical catalog and a pre-indexed offer read model. Retailer acquisition must run independently in the background. The proposed separation between catalog identity, commercial offers, connectors, validation, ranking and frontend is consistent with the Offer Platform v1 architecture.

This review records the decisions that should guide implementation.

## Accepted principles

1. Canonical perfume identity and retailer offers are separate entities.
2. Each retailer connector is isolated by retailer and market.
3. Source acquisition is multi-channel: approved APIs/feeds first where genuinely available, structured page data where reliable, retailer HTML as a controlled fallback, browser rendering only when needed.
4. Raw source evidence is retained with timestamps and parser versions.
5. Matching is exact-first and conservative. EAN/GTIN and verified retailer SKU mappings are strongest; brand/name/concentration/edition/size rules follow.
6. Tester, refill, gift set, mini, limited edition and concentration distinctions are explicit.
7. Public search reads a pre-indexed, validated offer model and never waits for every retailer.
8. Every offer has a source URL, currency, availability state and observed timestamp.
9. Connector failures are explicit and retailer-local; a timeout is not an empty search result.
10. Price history and match audit are first-class capabilities.

## Refinements and corrections

### A. Keep the architecture modular, but avoid premature infrastructure sprawl

FastAPI is already in use and should remain the API framework.

PostgreSQL is a likely target for multi-worker concurrency, durable relational history and operational reporting, but first measure SQLite contention, write volume, backup/recovery and worker topology. Do not migrate solely because PostgreSQL is fashionable.

Redis, Celery/Temporal, Meilisearch/OpenSearch, object storage and a full Prometheus/Grafana stack are optional decisions, not prerequisites for the first vertical slice. Introduce each only when a measured requirement justifies its operational cost.

A sensible sequence is:
- first: strict contracts, independent adapters, evidence capture and validated read model;
- next: durable scheduler/queue and database migration if the single-machine design is measurably limiting;
- later: dedicated search index/cache and expanded observability when catalog size and traffic justify them.

### B. Confidence scores do not authorize publication

A confidence score is useful for ranking review candidates and explaining a match. It is not proof.

Publication requires deterministic identity checks:
- exact canonical product and unique variant;
- exact size and concentration where applicable;
- edition/refill/tester/gift-set distinction;
- valid product URL and correct retailer market;
- valid price/currency and explicit availability evidence.

If an attribute needed to distinguish variants is absent or contradictory, the observation remains unresolved. No fuzzy score can override a hard mismatch.

### C. Source priority is retailer-specific

Approved APIs and feeds are preferred when they are authorized, complete and current. Structured page data can be excellent evidence. A retailer's official product page can also be a stronger source than a stale or incomplete feed.

Therefore source quality is measured per retailer/market using content-verified accuracy, completeness, freshness, stability, latency and cost. HTML is not automatically rejected; it is parsed and validated under a versioned adapter.

### D. Separate stock state from offer acquisition state

A retailer run can fail while a previous offer remains available as last-known-good data. Conversely, a successful page fetch can explicitly show out of stock.

Keep these concepts separate:
- adapter run status: success, timeout, blocked, parse error, credentials missing, etc.;
- offer availability: in_stock, out_of_stock, preorder, backorder, unknown;
- offer freshness: current, stale, expired.

A failed refresh must never turn a previous offer into out-of-stock or erase it. A stale offer must not be labelled freshly verified.

### E. Shipping and total price

The initial public comparison should distinguish item price from shipping. Do not claim "cheapest delivered" unless shipping to the user's destination is known and comparable. Keep the ranking policy transparent and configurable.

### F. Do not promise universal coverage

The system can promise correct handling of known catalog products and honest "no verified offer found" states. It cannot promise a live offer for every perfume or every shop. Coverage must be measured and reported per retailer, market and canonical variant.

## Data model additions

In addition to the entities in the proposal, implementation should include:

- `retailer_market`: canonical retailer + country/locale/currency + allowed hostnames.
- `retailer_candidate`: discovered listing identity and first/last seen.
- `raw_observation`: immutable response evidence, response hash, fetched time and parser version.
- `adapter_run`: per-market execution state, timing, counts and error classification.
- `canonical_match_audit`: rule applied, evidence fields, candidates and human review outcome.
- `current_offer`: validated latest state and freshness/expiry.
- `price_history`: immutable validated price/availability changes.

A canonical perfume product and a sellable product variant should remain distinct. The offer must point to the exact sellable variant, not only the fragrance family.

## Pilot and acceptance

The pilot should use a small but adversarial set of exact variants, not just easy products:

1. Liquid Brun standard 100 ml.
2. Liquid Brun Limited Edition 150 ml, including the known Bplatz out-of-stock regression.
3. Selected Born in Roma variants with different sizes/concentrations.

Then benchmark independent connectors for Bplatz, Deloox, Easycosmetic and Sabina before expanding to ParfumZentrum, ParfumCity, PerfumeMarket, Orioudh, Notino and Amazon DE/FR.

Each retailer/market must pass repeated live checks for:
- correct exact variant;
- correct country-specific product URL;
- correct price and currency;
- correct stock state;
- observation timestamp and source evidence;
- resilience when another retailer times out or is blocked.

Unit tests are necessary but never sufficient for a live integration.

## Final architecture decision

Use the Perplexity proposal as strategic validation of catalog-first, offer-indexed design. Use the Offer Platform v1 architecture as the implementation contract, with the refinements above.

Keep production and the current public search route unchanged until the new vertical slice demonstrates better exact-variant correctness and offer coverage in shadow mode.