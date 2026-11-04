from app.search import meilisearch


def test_meilisearch_disabled_returns_none(monkeypatch):
    monkeypatch.delenv("MEILISEARCH_URL", raising=False)
    assert meilisearch.search_variant_ids("Dior Sauvage") is None


def test_meilisearch_search_sends_catalog_filters(monkeypatch):
    monkeypatch.setenv("MEILISEARCH_URL", "http://meili.test")
    captured = {}

    def fake_request(method, path, payload=None):
        captured.update(method=method, path=path, payload=payload)
        return {"hits": [{"id": "variant-1"}, {"id": "variant-2"}]}

    monkeypatch.setattr(meilisearch, "_request", fake_request)
    result = meilisearch.search_variant_ids(
        "Dior Sauvage",
        filters={"family": "aromatic", "country": "LU", "format": "tester"},
    )
    assert result == ["variant-1", "variant-2"]
    assert captured["method"] == "POST"
    assert captured["path"] == "/indexes/scenthunter_products/search"
    assert captured["payload"]["q"] == "Dior Sauvage"
    assert captured["payload"]["filter"] == [
        'family = "aromatic"', 'format = "tester"', 'country = "LU"',
    ]


def test_meilisearch_failure_is_reported_for_fallback(monkeypatch):
    monkeypatch.setenv("MEILISEARCH_URL", "http://meili.test")

    def fail(*args, **kwargs):
        raise meilisearch.MeiliSearchUnavailable("TimeoutError")

    monkeypatch.setattr(meilisearch, "_request", fail)
    try:
        meilisearch.search_variant_ids("Dior Sauvage")
    except meilisearch.MeiliSearchUnavailable:
        pass
    else:
        raise AssertionError("Meilisearch failure should trigger PostgreSQL fallback")
