from fastapi.testclient import TestClient

import postgres_main


def test_postgres_homepage_redirects_to_catalog_first_demo():
    client = TestClient(postgres_main.app, follow_redirects=False)

    for path in ("/", "/frontend"):
        response = client.get(path)
        assert response.status_code == 307
        assert response.headers["location"] == "/catalog-demo"

    demo = client.get("/catalog-demo")
    assert demo.status_code == 200
    assert "Ricerca nel catalogo interno" in demo.text
    assert "/api/catalog/status" in demo.text
    assert "/api/catalog/search?q=" in demo.text
