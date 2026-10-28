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
def test_search_uses_public_html_fallback_when_creators_api_is_not_configured(monkeypatch, module, market):
    monkeypatch.delenv("AMAZON_CREATORS_API_COMPARISON_APPROVED", raising=False)
    monkeypatch.delenv("AMAZON_CREATORS_API_CLIENT_ID", raising=False)
    monkeypatch.delenv("AMAZON_CREATORS_API_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("AMAZON_ASSOCIATE_TAG_FR", raising=False)
    monkeypatch.delenv("AMAZON_ASSOCIATE_TAG_DE", raising=False)
    html = """
      <div data-component-type="s-search-result" data-asin="B012345678">
        <h2><span>French Avenue Liquid Brun Eau de Parfum 100 ml</span></h2>
        <span class="a-price"><span class="a-offscreen">39,90 €</span></span>
        <img class="s-image" src="https://images.example.test/item.jpg">
      </div>
    """
    class Response:
        status_code = 200
        url = module.BASE + "/s?k=Liquid+Brun"
        text = html
        def raise_for_status(self):
            return None
        def close(self):
            return None
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    report = module.search("Liquid Brun")
    assert report["status"] == "success"
    assert report["verified"] is True
    assert len(report["results"]) == 1
    assert report["results"][0]["store"] == f"amazon_{market}"
    assert report["results"][0]["price_num"] == 39.90
    assert report["details"]["source"] == "public_search_html"


@pytest.mark.parametrize(("module", "market"), [(fr, "fr"), (de, "de")])
def test_public_html_challenge_is_rejected_without_bypass(monkeypatch, module, market):
    class Response:
        status_code = 200
        url = module.BASE + "/s?k=Liquid+Brun"
        text = "<html><title>Robot Check</title><body>captcha</body></html>"
        def raise_for_status(self):
            return None
        def close(self):
            return None
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    report = module._public_html_search("Liquid Brun")
    assert report["status"] == "blocked"
    assert report["verified"] is False
    assert report["error"] == "amazon_challenge_page"


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

@pytest.mark.parametrize(("module", "market"), [(fr, "fr"), (de, "de")])
def test_external_bing_rss_fallback_requires_asin_matching_title_and_price(monkeypatch, module, market):
    xml = f"""<rss><channel><item>
      <title>French Avenue Liquid Brun Eau de Parfum 100 ml 39,90 €</title>
      <link>https://www.amazon.{market}/French-Avenue/dp/B012345678</link>
      <description>French Avenue Liquid Brun Eau de Parfum 100 ml: 39,90 €</description>
    </item><item>
      <title>Unrelated perfume 20,00 €</title>
      <link>https://www.amazon.{market}/dp/C012345678</link>
      <description>20,00 €</description>
    </item><item>
      <title>French Avenue Liquid Brun no price</title>
      <link>https://www.amazon.{market}/dp/D012345678</link>
      <description>Available online</description>
    </item></channel></rss>"""
    class Response:
        status_code = 200
        text = xml
        def close(self):
            return None
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    report = module._external_search_fallback("French Avenue Liquid Brun")
    assert report["status"] == "success"
    assert len(report["results"]) == 1
    assert report["results"][0]["url"] == f"https://www.amazon.{market}/dp/B012345678"
    assert report["results"][0]["price_num"] == 39.90
    assert report["details"]["source"] == "bing_rss_public_index"
    assert report["details"]["price_freshness"] == "search_engine_snippet_not_live_product_page"


@pytest.mark.parametrize(("module", "market"), [(fr, "fr"), (de, "de")])
def test_external_bing_rss_fallback_returns_none_without_price(monkeypatch, module, market):
    xml = f"""<rss><channel><item>
      <title>French Avenue Liquid Brun Eau de Parfum 100 ml</title>
      <link>https://www.amazon.{market}/dp/B012345678</link>
      <description>Product details, no current price displayed.</description>
    </item></channel></rss>"""
    class Response:
        status_code = 200
        text = xml
        def close(self):
            return None
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    assert module._external_search_fallback("French Avenue Liquid Brun") is None
