from fastapi.testclient import TestClient

import catalog_first_api


def test_search_start_returns_completed_catalog_contract(monkeypatch):
    called = {}

    def fake_search(query):
        called["query"] = query
        return {
            "query": query,
            "count": 1,
            "offer_count": 1,
            "results": [{
                "brand": "Dior",
                "fragrance": "Sauvage",
                "canonical_brand": "Dior",
                "canonical_name": "Sauvage",
                "catalog_id": "fixture-sauvage",
                "offers": [{
                    "store": "fixture-store",
                    "price": 89.9,
                    "currency": "EUR",
                    "url": "https://fixture.example/sauvage",
                }],
            }],
            "unresolved_offers": [],
            "identity_scope": [],
            "errors": {},
            "stores": {},
            "dedupe_diagnostics": [],
            "completed": True,
            "status": "completed",
        }

    monkeypatch.setattr(catalog_first_api, "search_catalog_for_frontend", fake_search)
    response = TestClient(catalog_first_api.app).get(
        "/search-start", params={"q": "Sauvage"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert called == {"query": "Sauvage"}
    assert payload["completed"] is True
    assert payload["status"] == "completed"
    assert payload["catalog_rollout"] == {
        "mode": "catalog",
        "environment": "staging",
        "traffic_percent": 100,
    }
    assert payload["results"][0]["brand"] == "Dior"


def test_search_start_rejects_short_queries():
    response = TestClient(catalog_first_api.app).get(
        "/search-start", params={"q": "D"}
    )
    assert response.status_code == 422


def test_frontend_is_served_by_the_same_api_origin():
    response = TestClient(catalog_first_api.app).get("/")
    assert response.status_code == 200
    assert "ScentHunter" in response.text


def test_catalog_health_route_reports_postgres_when_configured(monkeypatch):
    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, _statement):
            return 1

    class FakeEngine:
        dialect = type("Dialect", (), {"name": "postgresql"})()

        def connect(self):
            return FakeConnection()

        def dispose(self):
            return None

    monkeypatch.setattr(catalog_first_api, "make_engine", lambda: FakeEngine())
    response = TestClient(catalog_first_api.app).get("/healthz")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "service": "catalog-first-api",
        "database_dialect": "postgresql",
    }


def test_staging_fly_config_exposes_api_and_preserves_worker_isolation():
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "fly.staging-catalog.toml").read_text())
    assert config["app"] == "scenthunter-staging-workers"
    assert config["build"]["dockerfile"] == "backend/Dockerfile.worker"
    assert set(config["processes"]) == {"app", "web"}
    assert "beat" not in config["processes"]
    assert config["http_service"]["processes"] == ["web"]
    assert config["env"]["SCENTHUNTER_CATALOG_REQUIRE_POSTGRESQL"] == "1"
    assert all(vm["processes"] for vm in config["vm"])
    assert (root / "backend" / "start_api.sh").is_file()
