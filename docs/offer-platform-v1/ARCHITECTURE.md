# ScentHunter Offer Platform v1 — Architecture Decision

**Status:** proposed implementation baseline  
**Branch:** `architecture/clean-offer-platform-v1`  
**Production impact:** none. This branch is isolated from `main`; no deployment or production configuration changes are part of this work.

## 1. Objective

Build a perfume-specialist price comparison engine that returns **verified offers for the exact canonical variant**, not merely retailer search results that look similar.

The system must optimize four independent outcomes:

1. **Coverage:** discover the largest practical set of relevant retailer offers.
2. **Correctness:** never mix product, concentration, edition, or bottle size.
3. **Freshness:** make the age of every price and stock observation explicit.
4. **Resilience:** one blocked, slow, or broken retailer must not delay or erase results from the others.

A result is not considered successful merely because an HTTP request returned 200 or a unit test passed. A retailer observation is successful only when the expected product identity, variant, price/stock evidence, market and product URL have been validated.

## 2. Findings from the current repository

The current `main` branch already contains valuable components and must not be discarded blindly:

- `backend/catalog_engine.py` implements catalog-first discovery, local search and background product-page hydration. It is a 7,171-line module and currently combines transport, discovery, parsing, persistence, scheduling and status logic.
- Retailer-specific collectors already exist for Bplatz, Deloox, Easycosmetic, Notino, Orioudh, ParfumCity, ParfumZentrum, PerfumeMarket, Sabina and Amazon DE/FR.
- `backend/scenthunter_next_engine/` already has a conservative canonical matcher, normalized offer model and deterministic aggregation. It is read-only/opt-in and is not a live acquisition platform.
- `backend/main.py` contains operational resync endpoints and background thread orchestration. Search is catalog-first; it should remain so during migration.
- The next-engine normalizer intentionally accepts only explicit numeric size fields. That is safe, but it means retailer adapters must extract and provide the variant attributes explicitly.

**Conclusion:** the main gap is not a missing universal scraper. It is the absence of a clean, enforceable boundary between retailer acquisition, raw evidence, identity resolution, offer state and public search. Adding more orchestration to the existing monolith would deepen the coupling.

## 3. Target architecture

```text
                 ┌──────────────────────────┐
                 │     Search API / UI      │
                 │ cached verified offers  │
                 └────────────┬─────────────┘
                              │ read only
                 ┌────────────▼─────────────┐
                 │    Offer Read Model      │
                 │ exact variant + freshness│
                 └────────────┬─────────────┘
                              │
             ┌────────────────▼────────────────┐
             │       Offer State / History     │
             │ current snapshot + observations │
             └────────────────▲────────────────┘
                              │ validated writes
             ┌────────────────┴────────────────┐
             │   Identity + Offer Validator    │
             │ brand/product/edition/size/EDP  │
             └────────────────▲────────────────┘
                              │ raw observations
             ┌────────────────┴────────────────┐
             │       Acquisition Workers      │
             │ independent retailer jobs      │
             └───────┬───────────┬─────────────┘
                     │           │
              ┌──────▼─────┐ ┌───▼───────────┐
              │ Feeds/APIs │ │ HTML / browser│
              │ where real │ │ only per need │
              └──────┬─────┘ └───┬───────────┘
                     │           │
             ┌───────▼───────────▼────────────┐
             │   Retailer Adapter Registry    │
             │ one adapter = one retailer/    │
             │ market + explicit capabilities │
             └────────────────────────────────┘

     Canonical product/variant catalog is a separate, versioned input.
     Raw observations are retained for replay and audit.
```

### 3.1 Canonical catalog

The catalog owns product identity. Each sellable variant has a stable ID and explicit attributes:

- brand and product line;
- edition / flanker's name;
- concentration (EDP, EDT, parfum, extrait, etc.);
- size in ml;
- GTIN/EAN when known;
- aliases with provenance;
- active/inactive state.

A retailer listing never creates or changes a canonical product automatically. Unknown or ambiguous listings go to a review queue. The matcher must never infer 100 ml from 150 ml or collapse Limited Edition into the standard product.

### 3.2 Retailer adapter boundary

An adapter is configured by **retailer + market**, not retailer name alone. For example, Amazon DE and Amazon FR are different adapters; Deloox BE and Deloox NL must not silently share market URLs.

Every adapter implements the same contract:

- `discover(query or seed)`: return candidate product URLs/IDs and discovery evidence;
- `fetch_product(candidate)`: fetch one product page/feed record;
- `parse(raw)`: return typed observations, preserving the raw evidence reference;
- `healthcheck()`: verify the retailer is reachable and the parser still recognizes its page shape.

Each run returns one explicit state:
`success`, `verified_empty`, `out_of_stock`, `blocked`, `rate_limited`, `timeout`, `credentials_missing`, `parse_error`, `network_error`, or `disabled`.

A timeout is never converted into an empty result. A blocked page is never treated as a product page. A missing API credential is a configuration state, not a scraper bug.

### 3.3 Acquisition scheduling

Do not synchronously call every retailer from the user's search request.

- Discovery is scheduled independently per retailer/market.
- Product-page refresh is prioritized by requested canonical variants, offer age, retailer volatility and prior success.
- Search reads the last verified offer snapshot immediately.
- A stale offer may be displayed only with its observation time and stale label.
- A background refresh updates the result later; it cannot make the initial search wait for the slowest retailer.
- Per-retailer concurrency, request rate, retry policy and circuit breaker are isolated.

The first implementation can keep the current single-machine deployment. A durable queue or separate worker service is introduced only when measured load or process-restart behavior justifies it.

### 3.4 Identity and offer validation

A retailer observation becomes a public offer only after validation:

1. retailer and market are known from adapter configuration, not untrusted page text;
2. product URL is HTTPS and belongs to an allowed retailer host/market;
3. brand and product identity match the canonical catalog;
4. size and concentration match one unique canonical variant;
5. edition/refill/tester/gift-set distinctions are checked;
6. price is a valid positive amount and currency is explicit;
7. availability is supported by a positive or negative stock signal;
8. fetched time and evidence source are stored.

Matching order: exact GTIN/EAN or retailer product ID mapping; then exact canonical name/alias plus exact variant attributes; then unresolved/ambiguous review. Fuzzy title similarity may generate candidates for review, but must not publish a price.

### 3.5 Offer data model

Separate immutable evidence from the current read model.

- `retailer_candidate`: discovered URL, retailer, market, retailer product ID, first/last seen, discovery source.
- `raw_observation`: fetched timestamp, HTTP/result state, response hash, parser version, evidence pointer, raw attributes.
- `resolved_offer`: canonical product/variant IDs, normalized price/currency, stock state, market, canonical product URL, confidence/rule, observation ID.
- `current_offer`: one current best-known state per retailer-market-variant, including `observed_at`, `expires_at` and freshness.
- `adapter_run`: status, start/end, duration, counts, error class, parser version.

Raw observations are append-only. A parser correction can replay old evidence without scraping the retailer again. Current state is updated only by a validated observation; a failed refresh never overwrites a last-known-good offer.

### 3.6 Search read model

Search must be fast and predictable:

- query canonical product/variant catalog;
- read verified offers for the exact variant;
- sort by normalized price, with shipping treatment clearly defined;
- show retailer market and exact product URL;
- show stock state and observation age;
- return per-retailer freshness/status separately from offers.

Do not merge identical-looking URLs across markets unless canonical market equivalence is proven. Do not deduplicate two offers solely by title or price.

## 4. Performance and reliability policy

No provider or architecture is assumed to be universally best. A September 2026 public benchmark across 100 ecommerce domains reports material provider and domain variance; its own methodology correctly rejects HTTP 200 responses that contain challenge pages or empty shells. This supports benchmarking the actual ScentHunter retailer set rather than selecting a provider from marketing claims.

Benchmark each candidate transport on the same exact product URLs for Deloox, Bplatz, Easycosmetic, Sabina, Notino and Amazon DE/FR:

- at least 5 independent attempts per URL;
- content-verified success, not HTTP status;
- correct product/size/concentration;
- price and stock extraction accuracy;
- exact market URL;
- p50/p90 latency;
- cost per 1,000 valid observations;
- rate-limit/block behavior.

A generic browser or scraping API is a fallback transport, not the product identity engine. Keep a first-party adapter/parser where it performs better or returns stronger evidence.

**Initial performance targets are hypotheses, not guarantees:** cached search p95 below 1.5 seconds; no retailer refresh blocks the search response; every retailer has its own timeout and health state. Baseline and revise these targets using real deployment measurements.

## 5. Known access constraints

- Amazon DE/FR must use an approved API/feed when credentials are available. Public HTML may be blocked or incomplete. Never label missing credentials as a working integration.
- Notino affiliate/feed access is a separate capability from public search scraping. Verify credentials and terms before enabling the feed path.
- If a retailer blocks automated access, report that state. Do not bypass login, CAPTCHA or access controls.
- Market selection and affiliate URL rewriting must be explicit and tested. A Spanish Deloox URL must not appear for a Belgian/French/Luxembourg user unless that market is intentionally selected.

## 6. Migration strategy

Keep `main` and production behavior unchanged until the replacement proves parity.

1. **Inventory and baseline:** capture current search output, retailer health, current offer freshness and exact anchor products.
2. **Contracts:** define adapter result types, market config, canonical variant contract and immutable observation schema.
3. **One retailer vertical slice:** implement one adapter end-to-end, including evidence capture, parser, matching, persistence and public read model. Start with Bplatz or Deloox based on repeatable access.
4. **Anchor validation:** Liquid Brun 100 ml, Liquid Brun Limited Edition 150 ml, and selected Born in Roma variants. Confirm the 150 ml limited edition remains out of stock at Bplatz when the retailer says so.
5. **Retailer-by-retailer expansion:** add Easycosmetic, Sabina, ParfumZentrum, ParfumCity, PerfumeMarket, Orioudh, Deloox, Notino, Amazon FR and Amazon DE as independent adapters.
6. **Shadow comparison:** compare new and current outputs without writing to the public catalog.
7. **Canary:** expose a small controlled percentage only after exact-variant precision and offer coverage meet agreed thresholds.
8. **Cutover:** only with explicit approval and a rollback path.

No big-bang rewrite. No replacement of the stable search route until the new path wins on measured correctness and coverage.

## 7. Acceptance gates

A release cannot pass on unit tests alone.

- **Identity precision:** 100% on the curated anchor fixture set; no cross-size, cross-concentration or cross-edition match.
- **Price correctness:** every displayed amount agrees with the exact retailer page or approved feed at observation time.
- **Stock correctness:** explicit in-stock/out-of-stock evidence; unknown remains unknown.
- **URL correctness:** URL resolves to the right retailer, country market and exact product.
- **Isolation:** force one adapter to timeout/block/parse-error; all other adapters and search remain healthy.
- **Freshness:** every offer has a visible timestamp and a documented stale policy.
- **Replay:** stored raw evidence can be reparsed deterministically with a parser version.
- **Rollback:** feature flag off returns to the unchanged current search path.

## 8. Non-goals

- No AI/LLM decision on live price, stock or canonical identity.
- No automatic publication of fuzzy matches.
- No CAPTCHA/login bypass.
- No mandatory migration to Redis/Postgres before measurements show the existing persistence layer is the bottleneck.
- No production deployment in this architecture branch.
