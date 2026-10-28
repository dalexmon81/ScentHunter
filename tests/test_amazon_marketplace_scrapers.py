"""Contract tests for Amazon Creators API and bounded public search fallback."""
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
def test_search_restores_public_html_fallback_without_api_credentials(monkeypatch, module, market):
    monkeypatch.delenv("AMAZON_CREATORS_API_COMPARISON_APPROVED", raising=False)
    monkeypatch.delenv("AMAZON_CREATORS_API_CLIENT_ID", raising=False)
    monkeypatch.delenv("AMAZON_CREATORS_API_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("AMAZON_ASSOCIATE_TAG_FR", raising=False)
    monkeypatch.delenv("AMAZON_ASSOCIATE_TAG_DE", raising=False)

    html = """
    <html><body>
      <div data-component-type="s-search-result" data-asin="B012345678">
        <h2><a href="/dp/B012345678"><span>Liquid Brun Eau de Parfum 150 ml</span></a></h2>
        <span class="a-price"><span class="a-offscreen">49,90 €</span></span>
      </div>
    </body></html>
    """
    class Response:
        status_code = 200
        url = module.BASE + "/s?k=Liquid+Brun"
        text = html
        def raise_for_status(self):
            return None
        def close(self):
            return None
    calls = []
    def fake_get(url, **kwargs):
        calls.append(url)
        return Response()
    monkeypatch.setattr(module.requests, "get", fake_get)

    report = module.search("Liquid Brun")
    assert report["status"] == "success"
    assert report["verified"] is True
    assert len(report["results"]) == 1
    assert report["results"][0]["store"] == f"amazon_{market}"
    assert report["results"][0]["price_num"] == 49.90
    assert report["results"][0]["size_ml"] == 150
    assert calls == [module.BASE + "/s?k=Liquid+Brun"]


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
