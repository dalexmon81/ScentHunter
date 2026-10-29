"""Regression tests for bounded Notino external-discovery fallback."""

from backend.scrapers.notino import legacy_public


def test_price_bearing_search_result_returns_before_blocked_product_browser(monkeypatch):
    candidate = {
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "price_hint": "89,90€",
        "score": 100,
    }
    monkeypatch.setattr(
        legacy_public,
        "_discover",
        lambda query, session: ([candidate], {"primary_channel": "bing-rss"}),
    )
    monkeypatch.setattr(
        legacy_public,
        "_browser_fetch_products",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("price-bearing result should not wait on product browser")
        ),
    )

    rows = legacy_public.search("Dior Sauvage Eau de Parfum 100 ml")

    assert len(rows) == 1
    assert rows[0]["url"] == candidate["url"]
    assert rows[0]["price"] == "89,90€"
    assert rows[0]["price_source"] == "external_search_snippet"

def test_discovery_uses_external_rss_before_blocked_store_browser(monkeypatch):
    candidate = {
        "url": "https://www.notino.fr/dior/sauvage-eau-de-parfum/p-123456/",
        "name": "Dior Sauvage Eau de Parfum 100 ml",
        "price_hint": "89,90€",
        "score": 100,
    }
    monkeypatch.setattr(
        legacy_public,
        "_bing_rss",
        lambda query, session: ([candidate], {"engine": "bing-rss", "candidate_count": 1}),
    )
    monkeypatch.setattr(
        legacy_public,
        "_browser_search",
        lambda query: (_ for _ in ()).throw(
            AssertionError("Notino browser must not run before independent RSS discovery")
        ),
    )
    candidates, report = legacy_public._discover(
        "Dior Sauvage Eau de Parfum 100 ml",
        object(),
    )
    assert candidates == [candidate]
    assert report["primary_channel"] == "bing-rss"


def test_targeted_liquid_brun_notino_lookup_uses_live_exact_variant(monkeypatch):
    captured = {}
    class FakeSession:
        def close(self):
            pass
    monkeypatch.setattr(legacy_public, "_new_session", FakeSession)
    monkeypatch.setattr(legacy_public, "_reader_product", lambda session, candidate, query, _allow_variants=True: (
        captured.update({"url": candidate["url"], "allow_variants": _allow_variants})
        or {"name": "French Avenue Liquid Brun", "url": candidate["url"], "price": "48,00€", "size_ml": 100.0}
    ))
    rows = legacy_public._targeted_liquid_brun_result("French Avenue Liquid Brun 100 ml")
    assert captured["url"].endswith("p-16289640/")
    assert captured["allow_variants"] is False
    assert len(rows) == 1 and rows[0]["price"] == "48,00€"


def test_targeted_liquid_brun_notino_lookup_rejects_wrong_size(monkeypatch):
    class FakeSession:
        def close(self):
            pass
    monkeypatch.setattr(legacy_public, "_new_session", FakeSession)
    monkeypatch.setattr(legacy_public, "_reader_product", lambda *args, **kwargs: {
        "name": "French Avenue Liquid Brun Limited Edition", "url": "https://www.notino.fr/french-avenue/liquid-brun-limited-edition-extrait-de-parfum-mixte/p-16364075/",
        "price": "47,17€", "size_ml": 100.0,
    })
    assert legacy_public._targeted_liquid_brun_result("French Avenue Liquid Brun Limited Edition 150 ml") == []


def test_targeted_liquid_brun_notino_lookup_rejects_missing_price(monkeypatch):
    class FakeSession:
        def close(self):
            pass
    monkeypatch.setattr(legacy_public, "_new_session", FakeSession)
    monkeypatch.setattr(legacy_public, "_reader_product", lambda *args, **kwargs: {
        "name": "French Avenue Liquid Brun", "url": "https://www.notino.fr/french-avenue/liquid-brun-eau-de-parfum-mixte/p-16289640/",
        "price": "", "size_ml": 100.0,
    })
    assert legacy_public._targeted_liquid_brun_result("French Avenue Liquid Brun 100 ml") == []
