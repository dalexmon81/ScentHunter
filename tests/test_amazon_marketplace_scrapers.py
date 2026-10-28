"""Contract tests for approved Amazon Creators API marketplace adapters.

Comparative offers must not fall back to public HTML when API approval and
marketplace credentials are absent.
"""
import pytest

from backend.scrapers.amazon_fr import scraper as fr
from backend.scrapers.amazon_de import scraper as de


@pytest.mark.parametrize(
    ("module", "base", "language", "store_key"),
    [
        (fr, "https://www.amazon.fr", "fr-FR,fr;q=0.9,en;q=0.7", "amazon_fr"),
        (de, "https://www.amazon.de", "de-DE,de;q=0.9,en;q=0.7", "amazon_de"),
    ],
)
def test_marketplace_is_pinned_to_its_own_host(module, base, language, store_key):
    assert module.BASE == base
    assert module.HEADERS["Accept-Language"] == language
    assert module._allowed_product_url("/dp/B012345678") == f"{base}/dp/B012345678"
    foreign = "https://www.amazon.de/dp/B012345678" if store_key == "amazon_fr" else "https://www.amazon.fr/dp/B012345678"
    assert module._allowed_product_url(foreign) is None
    assert module._allowed_product_url("/s?k=parfum") is None
    assert module._allowed_product_url("/product-reviews/B012345678") is None


@pytest.mark.parametrize(("module", "market"), [(fr, "fr"), (de, "de")])
def test_search_refuses_unapproved_html_fallback(monkeypatch, module, market):
    monkeypatch.delenv("AMAZON_CREATORS_API_COMPARISON_APPROVED", raising=False)
    monkeypatch.delenv("AMAZON_CREATORS_API_CLIENT_ID", raising=False)
    monkeypatch.delenv("AMAZON_CREATORS_API_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("AMAZON_ASSOCIATE_TAG_FR", raising=False)
    monkeypatch.delenv("AMAZON_ASSOCIATE_TAG_DE", raising=False)

    def unexpected_request(*args, **kwargs):
        raise AssertionError("public Amazon HTML must not be requested")

    monkeypatch.setattr(module.requests, "get", unexpected_request)
    report = module.search("Liquid Brun")
    assert report["status"] == "unavailable"
    assert report["verified"] is False
    assert report["results"] == []
    assert report["error"] == "amazon_creators_api_not_configured_or_not_approved"
    assert report["details"]["market"] == market


@pytest.mark.parametrize(("module", "market"), [(fr, "fr"), (de, "de")])
def test_search_delegates_to_approved_creators_api(monkeypatch, module, market):
    expected = {
        "status": "success", "verified": True, "results": [
            {"store": f"amazon_{market}", "name": "Liquid Brun Eau de Parfum 150 ml",
             "size_ml": 150, "price_num": 79.9, "currency": "EUR",
             "availability": "IN_STOCK", "url": module.BASE + "/dp/B012345678"}
        ], "error": None, "details": {"market": market, "source": "amazon_creators_api"}
    }
    calls = []
    monkeypatch.setattr(module, "_creators_api_is_configured", lambda seen_market: seen_market == market)
    def fake_search(query, seen_market, store_key, size_parser, concentration_parser):
        calls.append((query, seen_market, store_key))
        return expected
    monkeypatch.setattr(module, "_creators_api_search", fake_search)

    report = module.search("Liquid Brun 150 ml")
    assert report == expected
    assert calls == [("Liquid Brun 150 ml", market, f"amazon_{market}")]
