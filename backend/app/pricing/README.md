# Pricing

**Responsibility:** validate observations for already-published offers, update current price and availability, apply source-timestamp rules, and append price history.

**Implementation ownership**
- `app.pricing.offer_refresh`: single implementation of verified offer refresh and price-history persistence.
- `app.models`: Offer, IngestionRaw and PriceHistory persistence entities.
- `app.workers`: schedules and invokes refreshes; it does not duplicate pricing rules.
- `app.connectors`: fetches retailer observations; pricing validates and persists them.

**Boundaries**
- Refresh only an existing offer; never discover products or change canonical product identity.
- No retailer HTTP calls from this package.
- Caller owns the database transaction.
- `app.services.offer_refresh` is a temporary compatibility re-export only.

**Tests:** `backend/tests/test_offer_refresh_persistence.py`.
