"""Contract tests for isolated Amazon marketplace adapters."""

from types import SimpleNamespace

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


@pytest.mark.parametrize("module", [fr, de])
def test_search_extracts_only_query_matching_priced_asin_products(monkeypatch, module):
    html = """
    <html><body>
      <div data-component-type="s-search-result" data-asin="B012345678">
        <h2><a href="/dp/B012345678"><span>Dior Sauvage Eau de Parfum 100 ml</span></a></h2>
        <span class="a-price"><span class="a-offscreen">99,90 €</span></span>
        <img class="s-image" src="https://images.example.test/item.jpg"/>
      </div>
      <div data-component-type="s-search-result" data-asin="B012345679">
        <h2><a href="/dp/B012345679"><span>Versace Blue Jeans 75 ml</span></a></h2>
        <span class="a-price"><span class="a-offscreen">22,00 €</span></span>
      </div>
      <div data-component-type="s-search-result" data-asin="B012345680">
        <h2><a href="/dp/B012345680"><span>Dior Sauvage Eau de Parfum 200 ml</span></a></h2>
      </div>
    </body></html>
    """
    class Response:
        status_code = 200
        url = module.BASE + "/s?k=Dior+Sauvage"
        text = html
        def raise_for_status(self):
            return None
        def close(self):
            return None
    captured = {}
    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return Response()
    monkeypatch.setattr(module.requests, "get", fake_get)

    report = module.search("Dior Sauvage")
    assert report["status"] == "success"
    assert report["verified"] is True
    assert len(report["results"]) == 1
    row = report["results"][0]
    assert row["store"] == ("amazon_fr" if module is fr else "amazon_de")
    assert row["url"] == module.BASE + "/dp/B012345678"
    assert row["price_num"] == 99.90
    assert row["size_ml"] == 100
    assert row["concentration"] == "Eau de Parfum"
    assert captured["url"].startswith(module.BASE + "/s?k=")
    assert captured["kwargs"]["headers"]["Accept-Language"] == module.LANGUAGE


@pytest.mark.parametrize(("module", "http_status"), [(fr, 403), (fr, 429), (fr, 503), (de, 403), (de, 429), (de, 503)])
def test_search_reports_http_failures_without_empty_success(monkeypatch, module, http_status):
    class Response:
        status_code = http_status
        url = module.BASE + "/s?k=parfum"
        text = "Service Unavailable"
        def raise_for_status(self):
            if self.status_code >= 400:
                raise module.requests.HTTPError(f"HTTP {self.status_code}")
        def close(self):
            return None
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    report = module.search("parfum")
    is_blocked = http_status in (403, 429)
    assert report["status"] == ("blocked" if is_blocked else "unavailable")
    assert report["verified"] is False
    assert report["results"] == []
    expected_error = f"blocked_http_{http_status}" if is_blocked else f"amazon_http_{http_status}"
    assert report["error"] == expected_error
    assert report["details"]["market"] == module.MARKET
    assert report["details"]["http_status"] == http_status


@pytest.mark.parametrize("module", [fr, de])
def test_search_reports_amazon_challenge_as_blocked_not_empty_success(monkeypatch, module):
    class Response:
        status_code = 200
        url = module.BASE + "/s?k=parfum"
        text = "<html>Robot Check - CAPTCHA</html>"
        def raise_for_status(self):
            return None
        def close(self):
            return None
    monkeypatch.setattr(module.requests, "get", lambda *args, **kwargs: Response())
    report = module.search("parfum")
    assert report["status"] == "blocked"
    assert report["verified"] is False
    assert report["results"] == []


@pytest.mark.parametrize(
    ("module", "market"),
    [(fr, "fr"), (de, "de")],
)
def test_amazon_comparison_never_falls_back_to_public_html_without_approval(monkeypatch, module, market):
    monkeypatch.delenv("AMAZON_CREATORS_API_COMPARISON_APPROVED", raising=False)
    monkeypatch.setenv("AMAZON_CREATORS_API_CLIENT_ID", "test-client")
    monkeypatch.setenv("AMAZON_CREATORS_API_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("AMAZON_ASSOCIATE_TAG_FR", "test-fr-21")
    monkeypatch.setenv("AMAZON_ASSOCIATE_TAG_DE", "test-de-21")

    def unexpected_request(*args, **kwargs):
        raise AssertionError("public Amazon HTML must not be requested")

    monkeypatch.setattr(module.requests, "get", unexpected_request)
    report = module.search("Liquid Brun")
    assert report["status"] == "unavailable"
    assert report["verified"] is False
    assert report["results"] == []
    assert report["error"] == "amazon_creators_api_not_configured_or_not_approved"
