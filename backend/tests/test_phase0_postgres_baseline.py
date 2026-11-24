from fastapi.testclient import TestClient

import postgres_main


def test_phase0_postgres_baseline_requires_token(monkeypatch):
    monkeypatch.setenv("SCENTHUNTER_BASELINE_TOKEN", "expected-token")
    client = TestClient(postgres_main.app)

    assert client.get("/admin/phase0/postgres-baseline").status_code == 401
    assert client.get(
        "/admin/phase0/postgres-baseline",
        headers={"Authorization": "Bearer wrong-token"},
    ).status_code == 401


def test_phase0_postgres_baseline_scope_is_nine_retailers():
    from app.api.phase0_baseline import STORE_SCOPE

    assert len(STORE_SCOPE) == 9
    assert {name for name, _slug in STORE_SCOPE} == {
        "bplatz", "deloox", "easycosmetic", "notino", "orioudh",
        "parfumcity", "parfumzentrum", "perfumemarket", "sabina",
    }
