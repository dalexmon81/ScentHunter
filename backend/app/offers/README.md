# Offers

**Responsibility:** own the lifecycle of retailer observations from staging through canonical match persistence, validation and publication of verified offers.

**Implementation ownership**
- `app.offers.ingestion`: shared orchestration for parsing connector records, invoking canonical matching, applying publication gates and promoting eligible offers.
- `app.offers.persistence`: single SQLAlchemy persistence gate for raw staging, legacy-ID mapping, match audit and offer promotion.
- `app.matching.canonical_matching`: decides the canonical variant; offers persists the decision but does not duplicate matching rules.
- `app.models`: Offer, IngestionRaw, MatchAudit and PriceHistory persistence entities.
- `app.pricing.offer_refresh`: updates already-published offers; it does not rediscover or rematch them.

**Boundaries**
- No retailer network calls or discovery; connectors and workers supply source observations.
- Publication requires a resolved canonical variant and explicit valid price, currency, availability and absolute HTTP(S) URL.
- Caller owns the database transaction.
- `app.services.connector_ingestion` and `app.services.ingestion_persistence` are temporary compatibility re-exports only.

**Tests:** `backend/tests/test_canonical_matching.py`, `backend/tests/test_phase2_bplatz_postgres.py`, and `tests/test_bplatz_persistence_service.py`.
