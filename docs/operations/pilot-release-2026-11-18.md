# Isolated pilot release — 2026-11-18

## Scope
- Deploy only `scenthunter-pilot-20261030` using `fly.staging.toml`.
- Keep the existing single Fly machine and mounted `scenthunter_pilot_data` volume.
- Use SQLite for the durable ingestion queue at `/data/catalog/ingestion_queue.sqlite3`.
- Run one queue worker in the same pilot machine as the API.
- Schedule Notino.fr discovery once per UTC day.
- Queue only validated feed rows with one unique canonical variant match.

## Cost boundary
No Managed PostgreSQL, Redis, Upstash, extra Fly app, extra volume, or extra machine is provisioned.

## Safety boundary
Production `main`, production `fly.toml`, and the production `scenthunter` app are not deployment targets.


Deployment trigger: the isolated pilot deploy workflow must run from this architecture branch only. No paid services are part of this release.


Final matching regression fix: concentration is derived from explicit retailer title text when the feed omits the dedicated field. Strict identity and ambiguity checks remain enabled.
