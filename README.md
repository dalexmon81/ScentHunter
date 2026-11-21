# ScentHunter

ScentHunter is a fragrance catalog and price-comparison service. The repository currently contains a production legacy runtime, a catalog-first application package, retailer connectors, background workers, migration tooling and isolated deployment/pilot configurations.

## Current runtime boundaries

- **Production Fly app:** `fly.toml` builds with the root `Dockerfile`. That image starts the existing `backend/main.py` FastAPI application, the family-coverage process and the Phase 0 baseline worker. Treat this as the production runtime; do not replace its entrypoint as part of repository cleanup.
- **Isolated Fly pilot:** `fly.staging.toml` explicitly selects `Dockerfile.pilot`. The pilot is API-only: it bootstraps its dedicated catalog volume and starts Uvicorn, but does not start the SQLite ingestion worker or automatic catalog discovery/hydration. The API-only guard also rejects legacy search, retailer resync, live diagnostics and Phase 0 job-start routes. It is not the production deployment. Runtime deployment remains separately gated and has not been performed.
- **Read-only catalog demo:** the root `catalog_demo_app.py` is a hosting shim for `backend/catalog_demo_app.py`. `start_catalog_demo.sh` starts the demo with a temporary SQLite database. Keep the shim and its backend app together.
- **Railway configuration:** `railway.toml` is a separate platform configuration. Its current deployment status is not established by this repository alone.

These deployment paths are intentionally distinct. Do not consolidate Dockerfiles, manifests, dependency files or app entrypoints without checking their deployment and CI references.

## Repository map

| Path | Responsibility |
| --- | --- |
| `backend/main.py`, `catalog_engine.py`, `product_matcher.py` | Existing production API, catalog and matching runtime |
| `backend/app/` | Catalog-first API, models, repositories, services, connectors and workers |
| `backend/alembic/` | Database schema migrations |
| `backend/scenthunter_next_engine/` | Optional next-engine implementation |
| `backend/scrapers/` | Retailer-specific scraping implementations |
| `backend/scripts/` | Backend maintenance, seed, migration and operator scripts |
| `backend/tests/`, `tests/` | Backend and repository-level regression tests |
| `tools/diagnostics/` | Retained operator diagnostics; scripts coupled to application routes remain available here |
| `.github/workflows/` | CI, diagnostics and explicitly controlled operational workflows |
| `docs/` | Architecture, migration and operations documentation |
| `frontend/index.html` | Existing frontend |

## Development and tests

Use Python 3.12. Backend dependencies are declared in `backend/requirements.txt`; the root `requirements.txt` is used by the root production Dockerfile. They are not interchangeable: the backend list currently includes the PostgreSQL driver.

Run backend tests from the backend directory:

```bash
cd backend
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```

Run repository-level tests from the repository root with the dependencies installed:

```bash
python -m unittest discover -s tests -v
```

Some workflows use pytest and install it explicitly. Follow the matching workflow when reproducing a CI check. Tests and local demo commands must use disposable databases; do not point them at production volumes.

## Safety rules

- Preserve `backend/product_catalog.json`, `backend/family_registry.json`, the production SQLite data and retailer fixtures.
- Do not remove legacy modules or retailer implementations merely because a newer package exists.
- Do not delete or disable workflows until their triggers, callers, artifacts and operational purpose have been checked.
- Do not run feed imports, production migrations, store activation, deployment or volume operations as part of cleanup.
- Production deployment and merge to protected `main` require separate review and approval.

For the current cleanup inventory and decisions, see [Issue #816](https://github.com/dalexmon81/ScentHunter/issues/816) and the architecture notes under `docs/architecture/`.
