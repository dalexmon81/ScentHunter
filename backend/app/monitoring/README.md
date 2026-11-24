# Monitoring

**Responsibility:** track connector health, consecutive failures, quarantine state and recovery evidence; expose operational signals for ingestion and offer freshness.

**Implementation ownership**
- `app.monitoring.connector_health`: single implementation for connector success/failure streaks and quarantine transitions.
- `app.models`: persisted Store and IngestionRun state.
- `app.workers`: calls monitoring actions at the boundaries of discovery, fetch and refresh jobs.
- API status routes expose read models; they do not implement health transitions.

**Boundaries**
- No retailer HTTP requests, scraping or job scheduling.
- A successful health signal is not proof that a connector returned valid products or publishable offers.
- `app.services.connector_health` is a temporary compatibility re-export only.

**Tests:** `backend/tests/test_connector_health.py`.
