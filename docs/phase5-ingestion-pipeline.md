# Phase 5 — Redis/Celery ingestion pipeline

## Architecture

The ingestion runtime is opt-in and separate from the API process. Redis is the
Celery broker; Celery Beat schedules background work. Six queues are declared:
`discovery`, `offers`, `validation`, `matching`, `refresh`, and
`dead_letter`.

Task flow:

1. `discover_store_products` runs a store connector and queues each discovered
   retailer product.
2. `fetch_store_offers` fetches offer records and stages them idempotently in
   `ingestion_raw`.
3. `normalize_offer` applies the canonical product normalizer.
4. `validate_offer` checks required evidence, URL, price, currency, timestamp
   and availability without inventing missing values.
5. `match_offer_to_variant` delegates to the existing conservative UUID matcher.
6. Publication remains a separate explicit worker; ingestion never publishes
   an unmatched or unvalidated offer.
7. `refresh_price_and_stock` stages a new observation for a known retailer ID.
8. Failed tasks are retried with exponential backoff and jitter. Exhausted tasks
   are sent to the `dead_letter` queue and repeated store failures trigger the
   store-scoped quarantine check.

The `ingestion_artifacts` table stores immutable source bytes with SHA-256,
format, content type, source URL, capture time and run reference. Notino's
affiliate XML feed is retained byte-for-byte. The shared `LegacyStoreConnector`
now uses a request-scoped `requests.Session` subclass to retain exact response
bodies for successful HTML, XHTML, JSON, CSV and XML product-page requests.
This covers the page-parser path used by Bplatz, Orioudh, PerfumeMarket and
ParfumCity when that path is invoked; binary assets and failed responses are
not retained. The adapters also retain their raw structured discovery output.
Deloox, Easycosmetic, Sabina and Parfumzentrum still use their own search/page
paths and do not yet guarantee original HTML/CSV body capture. Therefore
byte-for-byte HTML/CSV coverage is improved but not complete across all nine
stores. Each staged offer records the artifact IDs in its `_raw_evidence`
envelope.

## Cadence

Celery Beat defaults:
- Product discovery: every 24 hours.
- New offer collection: every 8 hours.
- Main-store price/stock refresh: every 30 minutes, only for stores explicitly
  listed in `SCENTHUNTER_MAIN_REFRESH_STORES`.

A product-detail handler can call
`enqueue_product_detail_refresh(store_key, offer_id)` when the user opens a
detail page. This dispatches the retailer refresh onto the `refresh` queue and
returns its Celery job ID. The existing public product-detail HTTP handler and
frontend have not yet been connected to this dispatch helper.

### Detail-refresh integration

The backend exposes `POST /catalog/offers/{offer_id}/refresh`. It accepts
only the persisted Offer UUID; store slug and retailer product ID are resolved
from the database. It rejects missing/inactive offers and offers without a
stable retailer ID, uses Redis `SET NX EX` for a five-minute per-offer
cooldown, and releases the cooldown if Celery enqueueing fails. Redis failure
fails closed with HTTP 503. A browser cannot supply an arbitrary store or SKU.

The read-only endpoint `GET /catalog/legacy-products/{legacy_product_id}/offers`
bridges the existing frontend product ID through `legacy_product_id_map` to
matched Phase 2 variants and active offers. It returns the persisted Offer UUID,
retailer slug, exact URL and variant size. It never infers an ID from a URL or
SKU. On product/format detail open, the frontend requests this endpoint and
attaches the UUID only when URL and variant size identify exactly one returned
offer. If the map or Phase 2 database is empty, the legacy detail continues
unchanged. The “Aggiorna prezzo” control is therefore shown only for a verified
match.

Dedicated tests cover active-offer resolution, inactive-store rejection,
missing retailer IDs, cooldown behavior, cooldown release after enqueue
failure, legacy ID mapping, exact persisted UUID return, and rejection of
unmapped or inactive offers. The frontend bridge is wired, but still requires
end-to-end verification against a populated Phase 2 database and running
Redis/Celery services.

## Configuration

Required:
- `SCENTHUNTER_CATALOG_DATABASE_URL`: existing Phase 2 catalog database URL.
- `SCENTHUNTER_REDIS_URL`: Redis broker URL (default local Redis).
- `SCENTHUNTER_DISCOVERY_TERMS_JSON`: optional JSON object mapping store slugs
  to discovery search terms. Example:
  `{"deloox":["Dior Sauvage 100 ml"],"sabina":["Chanel No 5"]}`.
- `SCENTHUNTER_MAIN_REFRESH_STORES`: comma-separated store slugs opted into
  the 30-minute refresh schedule.
- `SCENTHUNTER_CONNECTOR_QUARANTINE_AFTER`: consecutive failures before
  quarantine (default 3).

No schema migration or production service is run automatically. Before starting workers, apply the new additive migrations with
`cd backend && alembic upgrade head`. The deployment must supply the existing
catalog DB URL and explicit store configuration.

## Local opt-in

```bash
docker compose -f docker-compose.ingestion.yml up -d redis celery-worker celery-beat
```

This starts only the optional ingestion services. It does not deploy the API or
enable user-search-time scraping.

## Verification

New additive schema revisions: `0006_ingestion_artifacts` and
`0007_ingestion_dead_letters`. They add immutable raw artifact storage and a
durable dead-letter record table.

The Phase 5 GitHub Actions workflow compiles the worker/connector modules and
runs the ingestion, matching, promotion and queue configuration tests. Passing
fixture tests do not prove live retailer credentials, live store reachability,
or production worker activation.


## Stato aggiornato — 4 novembre 2026

La vista dettaglio frontend usa già l'endpoint legacy-ID bridge e associa l'UUID Phase 2 soltanto quando URL e formato individuano una singola offerta persistita. Il comando di aggiornamento è disponibile solo dopo questa verifica.

La cattura del body HTML è stata estesa anche ai page-loader indipendenti di Deloox, Easycosmetic, Sabina e Parfumzentrum. I byte originali vengono salvati con URL sorgente e store. La cattura avviene quando il page-loader restituisce il body; non significa che ogni ricerca abbia necessariamente scaricato la pagina prodotto.

La pianificazione periodica ora seleziona soltanto i negozi con una riga Phase 2 in stato `active`. Il worker di discovery, il salvataggio degli artefatti e il refresh verificano nuovamente lo stato prima di procedere.

La seed Phase 2 importa identità canoniche e mappe legacy, ma non importa offerte (`offers_imported = 0`). Bplatz è il solo negozio attivato dalla seed pilota; gli altri restano configurabili e gestiti esplicitamente dall'operatore.

Ultima CI verificata sul commit `296ce33d982e0764add98e8f9b3faf2236435af7`: workflow Phase 5 e workflow contratti connector Phase 4 entrambi superati; Phase 5: 38 test passati. I test fixture non sostituiscono una prova live con database, Redis, worker e negozi reali.
