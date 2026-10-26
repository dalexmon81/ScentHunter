import pytest

from backend.scrapers import amazon_creators_api as api


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self.payload = payload or {}
        self.closed = False

    def json(self):
        return self.payload

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def reset_token_cache(monkeypatch):
    api._TOKEN_CACHE.update({"client_id": None, "access_token": None, "expires_at": 0.0})
    monkeypatch.setenv("AMAZON_CREATORS_API_CLIENT_ID", "test-client")
    monkeypatch.setenv("AMAZON_CREATORS_API_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("AMAZON_ASSOCIATE_TAG_FR", "scenthunterfr-21")
    monkeypatch.setenv("AMAZON_ASSOCIATE_TAG_DE", "scenthunterde-21")
    yield
    api._TOKEN_CACHE.update({"client_id": None, "access_token": None, "expires_at": 0.0})


def test_api_requires_credentials_and_marketplace_tag(monkeypatch):
    monkeypatch.delenv("AMAZON_CREATORS_API_CLIENT_SECRET")
    assert api.is_configured("fr") is False
    monkeypatch.setenv("AMAZON_CREATORS_API_CLIENT_SECRET", "test-secret")
    monkeypatch.delenv("AMAZON_ASSOCIATE_TAG_DE")
    assert api.is_configured("de") is False
    assert api.is_configured("fr") is True


@pytest.mark.parametrize(("market", "tag", "host"), [
    ("fr", "AMAZON_ASSOCIATE_TAG_FR", "www.amazon.fr"),
    ("de", "AMAZON_ASSOCIATE_TAG_DE", "www.amazon.de"),
])
def test_search_uses_official_marketplace_and_returns_only_priced_offers(monkeypatch, market, tag, host):
    token_response = Response(payload={"access_token": "test-token", "expires_in": 3600})
    api_response = Response(payload={
        "searchResult": {
            "totalResultCount": 1,
            "items": [{
                "asin": "B012345678",
                "detailPageURL": f"https://{host}/dp/B012345678?tag=partner-21",
                "images": {"primary": {"medium": {"url": "https://images.example.invalid/item.jpg"}}},
                "itemInfo": {
                    "title": {"displayValue": "Dior Sauvage Eau de Parfum 100 ml"},
                    "byLineInfo": {"brand": {"displayValue": "Dior"}},
                },
                "offersV2": {"listings": [{
                    "price": {"money": {"amount": 89.95, "currency": "EUR", "displayAmount": "89,95 €"}},
                    "availability": {"type": "IN_STOCK"},
                }]},
            }, {
                "asin": "B012345679",
                "detailPageURL": f"https://{host}/dp/B012345679",
                "itemInfo": {"title": {"displayValue": "Dior Sauvage Eau de Parfum 60 ml"}},
                "offersV2": {"listings": []},
            }],
        },
    })
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return token_response if url.endswith("/auth/o2/token") else api_response

    monkeypatch.setattr(api.requests, "post", fake_post)
    report = api.search_marketplace(
        "Dior Sauvage", market, f"amazon_{market}",
        lambda title: 100 if "100 ml" in title else None,
        lambda title: "Eau de Parfum" if "Eau de Parfum" in title else None,
    )

    assert report["status"] == "success"
    assert report["verified"] is True
    assert report["details"]["source"] == "amazon_creators_api"
    assert len(report["results"]) == 1
    offer = report["results"][0]
    assert offer["store"] == f"amazon_{market}"
    assert offer["name"] == "Dior Sauvage Eau de Parfum 100 ml"
    assert offer["price_num"] == 89.95
    assert offer["currency"] == "EUR"
    assert offer["url"].startswith(f"https://{host}/dp/B012345678")
    assert offer["brand"] == "Dior"
    assert calls[0][0] == api.DEFAULT_TOKEN_URL
    assert calls[1][0] == api.API_BASE + "/catalog/v1/searchItems"
    assert calls[1][1]["headers"]["x-marketplace"] == host
    assert calls[1][1]["json"]["marketplace"] == host
    assert calls[1][1]["json"]["partnerTag"] == __import__("os").environ[tag]
    assert token_response.closed and api_response.closed


@pytest.mark.parametrize(("http_status", "expected_status", "expected_error"), [
    (403, "blocked", "amazon_creators_api_access_denied"),
    (503, "unavailable", "amazon_creators_api_http_error"),
    (429, "unavailable", "amazon_creators_api_rate_limited"),
])
def test_api_http_errors_never_become_empty_success(monkeypatch, http_status, expected_status, expected_error):
    token_response = Response(payload={"access_token": "test-token", "expires_in": 3600})
    api_response = Response(status_code=http_status)
    monkeypatch.setattr(api.requests, "post", lambda url, **kwargs: (
        token_response if url.endswith("/auth/o2/token") else api_response
    ))
    report = api.search_marketplace("parfum", "fr", "amazon_fr", lambda _: None, lambda _: None)
    assert report["status"] == expected_status
    assert report["verified"] is False
    assert report["results"] == []
    assert report["error"] == expected_error
    assert report["details"]["http_status"] == http_status


def test_foreign_product_url_is_not_returned(monkeypatch):
    token_response = Response(payload={"access_token": "test-token", "expires_in": 3600})
    api_response = Response(payload={"searchResult": {"items": [{
        "asin": "B012345678",
        "detailPageURL": "https://www.amazon.de/dp/B012345678",
        "itemInfo": {"title": {"displayValue": "Parfum 100 ml"}},
        "offersV2": {"listings": [{
            "price": {"money": {"amount": 12.5, "currency": "EUR"}},
        }]},
    }]}})
    monkeypatch.setattr(api.requests, "post", lambda url, **kwargs: (
        token_response if url.endswith("/auth/o2/token") else api_response
    ))
    report = api.search_marketplace("parfum", "fr", "amazon_fr", lambda _: 100, lambda _: None)
    assert report["status"] == "success"
    assert report["results"] == []



def test_catalog_discovery_keeps_canonical_urls_even_without_price(monkeypatch):
    token_response = Response(payload={"access_token": "test-token", "expires_in": 3600})
    api_response = Response(payload={"searchResult": {"items": [
        {
            "asin": "B012345678",
            "detailPageURL": "https://www.amazon.fr/dp/B012345678?tag=partner-21",
            "itemInfo": {"title": {"displayValue": "Parfum de test"}},
        },
        {
            "asin": "B012345679",
            "detailPageURL": "https://www.amazon.de/dp/B012345679",
            "itemInfo": {"title": {"displayValue": "Parfum étranger"}},
        },
        {
            "asin": "B012345680",
            "detailPageURL": "https://www.example.invalid/dp/B012345680",
            "itemInfo": {"title": {"displayValue": "Foreign host"}},
        },
    ]}})
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return token_response if url.endswith("/auth/o2/token") else api_response

    monkeypatch.setattr(api.requests, "post", fake_post)
    report = api.discover_product_urls("fr", max_queries=1)
    assert report["status"] == "success"
    assert report["urls"] == ["https://www.amazon.fr/dp/B012345678"]
    assert calls[1][0] == api.API_BASE + "/catalog/v1/searchItems"
    assert calls[1][1]["json"]["resources"] == ["itemInfo.title"]


def test_get_product_hydrates_current_priced_offer_via_api(monkeypatch):
    token_response = Response(payload={"access_token": "test-token", "expires_in": 3600})
    api_response = Response(payload={"itemsResult": {"items": [{
        "asin": "B012345678",
        "detailPageURL": "https://www.amazon.de/dp/B012345678?tag=partner-21",
        "images": {"primary": {"medium": {"url": "https://images.example.invalid/item.jpg"}}},
        "itemInfo": {
            "title": {"displayValue": "Dior Sauvage Eau de Parfum 100 ml"},
            "byLineInfo": {"brand": {"displayValue": "Dior"}},
        },
        "offersV2": {"listings": [{
            "price": {"money": {"amount": 89.95, "currency": "EUR"}},
            "availability": {"type": "IN_STOCK"},
        }]},
    }]}})
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return token_response if url.endswith("/auth/o2/token") else api_response

    monkeypatch.setattr(api.requests, "post", fake_post)
    item = api.get_product(
        "de", "B012345678",
        lambda title: 100 if "100 ml" in title else None,
        lambda title: "Eau de Parfum" if "Eau de Parfum" in title else None,
    )
    assert item["store_key"] == "amazon_de"
    assert item["name"] == "Dior Sauvage Eau de Parfum 100 ml"
    assert item["price_num"] == 89.95
    assert item["currency"] == "EUR"
    assert item["availability"] == "in_stock"
    assert item["source"] == "amazon_creators_api"
    assert item["url"].startswith("https://www.amazon.de/dp/B012345678")
    assert calls[1][0] == api.API_BASE + "/catalog/v1/getItems"
    assert calls[1][1]["json"]["itemIds"] == ["B012345678"]
