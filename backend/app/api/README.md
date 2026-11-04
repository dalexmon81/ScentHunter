# API layer

HTTP routers and request/response handling only. Keep business rules in services; do not call store connectors directly from request handlers.

## Catalog-first public API

All public catalog routes use the `/api` namespace:

- `GET /api/search` — indexed catalog search with brand, family, gender, concentration, format, store, availability, country, currency and price filters.
- `GET /api/products/{slug}` — canonical product and variant selection.
- `GET /api/products/{slug}/offers?variant_id=...` — ranked offers for one explicit variant.
- `GET /api/products/{slug}/price-history?variant_id=...` — per-currency price minimum, average, trend and anomaly alert.
- `GET /api/brands` and `GET /api/stores` — filter options.
- `GET /api/offers` — ranked published offers with optional store and availability filters.
- `POST /api/offers/{offer_id}/refresh` — enqueue a bounded, offer-scoped price refresh; it does not synchronously scrape a retailer.

Search reads the persisted catalog only. A refresh request queues a background task and does not claim that the displayed price has already changed.

## Protected administration API

The following read-only operational views require `Authorization: Bearer <token>`:

- `GET /api/admin/connectors`
- `GET /api/admin/ingestion`
- `GET /api/admin/matching`

Set `SCENTHUNTER_ADMIN_TOKEN` in the API environment. If it is unset, the admin API returns `503 admin_api_not_configured`; it never silently exposes operational data.

## Contracts

Transport contracts live in `app/schemas/catalog.py` and use Pydantic v2. Keep persistence models out of public response payloads. Admin endpoints are read-only in this phase; review decisions and connector control actions require separate authorization and audit design.
