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
