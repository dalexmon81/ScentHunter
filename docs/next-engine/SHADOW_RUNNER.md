# Offline shadow runner (iPhone-friendly instructions)

This tool compares **two JSON snapshots that have already been exported**. It does not connect to SQLite, access the live site, send HTTP requests, or modify either catalog.

## Snapshot format

Each input may be a JSON array of row objects, or an object with a `rows` array. Rows should include as many of these fields as possible: `store`, `brand`, `name`, `size_ml`, `concentration`, `price` (or `price_minor`), `currency`, `url` (or `product_url`).

## Run it in a Python environment

From the repository root, after placing this package under `backend/scenthunter_next_engine/` and setting `PYTHONPATH=backend`:

```sh
python -m scenthunter_next_engine.shadow_runner --legacy /path/legacy.json --next /path/next.json --output /path/shadow-report.json
```

The report records product coverage, missing rows, URL differences, currency mismatches and price differences. It refuses to overwrite either input.

## Important boundary

A schema-aware exporter now exists in `scenthunter_next_engine.sqlite_export` and emits the three legacy tables as JSON. The runner accepts that snapshot directly, preferring persisted variants when present. The exporter is tested only against a temporary fixture database so far; it has **not** read the production SQLite file, and this does not establish live shadow parity. See `SQLITE_EXPORT.md`.
