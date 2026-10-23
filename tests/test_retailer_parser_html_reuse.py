from backend.scrapers.deloox import scraper as deloox
from backend.scrapers.parfumzentrum import scraper as parfumzentrum


def test_deloox_html_adapter_reuses_supplied_body(monkeypatch):
    body = '<html><script type="application/ld+json">{}</script></html>'
    seen = {}

    def fake_product(url, html, query):
        seen.update(url=url, html=html, query=query)
        return {"name": "Acqua di Gio Profondo EDP", "size_ml": 125}

    monkeypatch.setattr(deloox, "_product", fake_product)
    result = deloox.extract_product_html(
        "https://www.deloox.nl/en/product/123/example",
        body,
        "Acqua di Gio Profondo EDP 125 ml",
    )
    assert result["size_ml"] == 125
    assert seen["html"] == body
    assert seen["url"].startswith("https://")


def test_parfumzentrum_adapter_reuses_supplied_body(monkeypatch):
    body = '<html><h1>Acqua di Gio Profondo Eau de Parfum 125 ml</h1></html>'
    seen = {}

    def fake_extract(url, query, html=None):
        seen.update(url=url, query=query, html=html)
        return {"name": "Acqua di Gio Profondo EDP", "size_ml": 125}

    monkeypatch.setattr(parfumzentrum, "_extract_product", fake_extract)
    result = parfumzentrum.extract_product_page(
        None,
        "https://www.parfum-zentrum.de/acqua-di-gio-profondo-edp_z123",
        "Acqua di Gio Profondo EDP 125 ml",
        html=body,
    )
    assert result["size_ml"] == 125
    assert seen["html"] == body
    assert seen["url"].endswith("_z123")
