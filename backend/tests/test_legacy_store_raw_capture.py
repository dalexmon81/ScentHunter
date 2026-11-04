import asyncio
from types import SimpleNamespace

import requests

from app.connectors.legacy_store import LegacyStoreConnector


def _fake_response(url, content_type, body, status=200):
    response = requests.Response()
    response.status_code = status
    response.url = url
    response.headers["Content-Type"] = content_type
    response._content = body
    return response


def test_legacy_page_parser_captures_exact_html_response(monkeypatch):
    url = "https://shop.example/products/perfume"
    body = b"<html><body>Original response bytes</body></html>"
    response = _fake_response(url, "text/html; charset=utf-8", body)
    monkeypatch.setattr(requests.Session, "request", lambda self, method, request_url, *a, **k: response)

    scraper = SimpleNamespace(search=lambda _query: [])
    def page_parser(session, page_url, _query):
        return session.get(page_url).text

    connector = LegacyStoreConnector(
        "fixture-store", scraper, page_parser=page_parser, discovery_terms=("test",)
    )
    parsed = asyncio.run(connector._load_page(url, "test"))

    assert parsed == body.decode("utf-8")
    assert connector._raw_artifacts == [{
        "format": "html",
        "data": body,
        "content_type": "text/html",
        "source_url": url,
        "metadata": {"http_status": 200, "method": "GET"},
    }]


def test_legacy_page_capture_ignores_binary_and_failed_responses(monkeypatch):
    url = "https://shop.example/assets/photo.jpg"
    response = _fake_response(url, "image/jpeg", b"binary-image")
    monkeypatch.setattr(requests.Session, "request", lambda self, method, request_url, *a, **k: response)
    artifacts = []
    from app.connectors.legacy_store import _ArtifactCapturingSession

    with _ArtifactCapturingSession(artifacts) as session:
        session.get(url)
    assert artifacts == []

    failed = _fake_response("https://shop.example/blocked", "text/html", b"blocked", status=403)
    monkeypatch.setattr(requests.Session, "request", lambda self, method, request_url, *a, **k: failed)
    with _ArtifactCapturingSession(artifacts) as session:
        session.get(failed.url)
    assert artifacts == []


def test_independent_scraper_page_loaders_retain_exact_html_bytes(monkeypatch):
    from datetime import datetime, timezone
    from decimal import Decimal

    from app.connectors.base import OfferRecord
    from app.connectors.deloox import DelooxConnector
    from app.connectors.easycosmetic import EasycosmeticConnector
    from app.connectors.sabina import SabinaConnector
    from app.connectors.parfumzentrum import ParfumzentrumConnector

    url = "https://shop.example/products/perfume"
    body = b"<html><body>exact retailer response</body></html>"
    record = OfferRecord(
        store="fixture-store", external_product_id="sku-1",
        brand="Test Brand", fragrance="Test Perfume", concentration="EDP",
        size_ml=100, gtin=None, title="Test Perfume EDP 100 ml",
        url=url, price=Decimal("49.90"), currency="EUR",
        availability="in_stock", captured_at=datetime.now(timezone.utc).isoformat(),
        source="fixture",
    )

    connectors = [
        (DelooxConnector(page_loader=lambda _url: (url, body, "test")), (url, body, "test")),
        (EasycosmeticConnector(page_loader=lambda _url: (url, body)), (url, body)),
        (SabinaConnector(page_loader=lambda _url: (url, body)), (url, body)),
        (ParfumzentrumConnector(page_loader=lambda _url: (url, body)), (url, body)),
    ]
    for connector, loaded in connectors:
        monkeypatch.setattr(connector, "parse_raw", lambda _raw: (record,))
        asyncio.run(connector.fetch_product(url))
        assert connector._raw_artifacts == [{
            "format": "html",
            "data": body,
            "content_type": "text/html",
            "source_url": url,
            "metadata": {"capture": "page_loader_body", "store": connector.store_key},
        }]
