# Discovery

**Responsibility:** turn a retailer discovery page into durable background fetch work. This layer owns pagination continuation and dispatch of stable retailer product references.

**Implementation ownership**
- `app.discovery.dispatch`: one shared implementation for dispatching every discovered reference, recording enqueue errors and scheduling the next page.
- `app.connectors`: performs retailer-specific discovery I/O and returns `DiscoveredProduct` references.
- `app.workers`: owns job execution, retries, run accounting and connector health.
- `app.offers`: fetches/persists product observations, performs canonical matching and applies publication gates.

**Boundaries**
- Discovery does not perform canonical matching and must not filter candidates based on a legacy catalog.
- Discovery never publishes offers and never runs during user search.
- Every discovered reference is sent to the shared fetch pipeline; unresolved identities remain staged for review.
- The dispatch function is pure orchestration: queue backends are injected by the worker, not selected here.

**Tests:** `backend/tests/test_discovery_dispatch.py`, plus Notino and legacy worker runtime regression suites.
