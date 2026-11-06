from pathlib import Path
import asyncio

from app.connectors.easycosmetic import EasycosmeticConnector

FIXTURE = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "connectors" / "easycosmetic-product.html"
URL = "https://www.easycosmetic.de/p/dior-sauvage-edp-100ml"


def test_easycosmetic_saved_product_fixture_maps_to_universal_offer():
    connector = EasycosmeticConnector()
    records = connector.parse_raw((URL, FIXTURE.read_text(encoding="utf-8")))
    assert len(records) == 1
    offer = records[0]
    assert offer.store == "easycosmetic"
    assert offer.brand == "Dior"
    assert offer.fragrance == "sauvage"
    assert offer.concentration == "edp"
    assert offer.size_ml == 100
    assert offer.price is not None and str(offer.price) == "84.95"
    assert offer.currency == "EUR"
    assert offer.availability == "in_stock"
    assert connector.validate_offer(offer)[0]


def test_easycosmetic_unknown_stock_is_not_invented():
    connector = EasycosmeticConnector()
    row = {"name": "Dior Sauvage Eau de Parfum 100 ml", "brand": "Dior",
           "url": URL, "price_num": 84.95, "currency": "EUR",
           "availability": "", "available": None, "size_ml": 100}
    offer = connector.parse_raw(row)[0]
    assert offer.availability == "unknown"


def test_easycosmetic_discovery_uses_injected_search():
    row = {"name": "Dior Sauvage Eau de Parfum 100 ml", "brand": "Dior",
           "url": URL, "price_num": 84.95, "currency": "EUR",
           "availability": "In stock", "available": True, "size_ml": 100}
    connector = EasycosmeticConnector(["Dior Sauvage"], search_func=lambda query: [row])
    async def run():
        found = await connector.discover_products()
        assert len(found) == 1
        offers = await connector.fetch_offers(URL)
        assert len(offers) == 1
    asyncio.run(run())


@pytest.mark.parametrize("status_code", [403, 429])
def test_easycosmetic_does_not_use_browser_fallback_after_access_denial(
    monkeypatch, status_code
):
    from types import ModuleType
    from scrapers.easycosmetic import scraper

    # The fake Playwright module makes any attempted browser fallback observable.
    calls = {"http": 0, "browser": 0}

    class Response:
        url = URL
        text = "<html></html>"

        def __init__(self):
            self.status_code = status_code

        def close(self):
            pass

    def fake_get(*args, **kwargs):
        calls["http"] += 1
        return Response()

    def forbidden_browser():
        calls["browser"] += 1
        raise AssertionError("browser fallback must not run after 403/429")

    monkeypatch.setattr(scraper.requests, "get", fake_get)
    playwright_package = ModuleType("playwright")
    playwright_package.__path__ = []
    playwright_sync_api = ModuleType("playwright.sync_api")
    playwright_sync_api.sync_playwright = forbidden_browser
    monkeypatch.setitem(__import__("sys").modules, "playwright", playwright_package)
    monkeypatch.setitem(
        __import__("sys").modules, "playwright.sync_api", playwright_sync_api
    )

    with pytest.raises(scraper.StoreRequestError) as caught:
        scraper._request_html(URL)

    assert caught.value.status == "blocked"
    assert caught.value.http_status == status_code
    assert calls == {"http": 1, "browser": 0}
