from backend.scrapers.deloox import scraper as deloox
from backend.scrapers.parfumzentrum import scraper as parfumzentrum


def test_deloox_html_adapter_reuses_supplied_body(monkeypatch):
    body = '<html><h1>Acqua di Gio Profondo Eau de Parfum 125 ml</h1><script type="application/ld+json">{}</script></html>'
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


"""Regression tests for real product-page extraction logic using fixed fixtures.

These tests exercise the retailer parsers directly. Fixtures are intentionally
synthetic and validate extraction only; they do not prove a retailer currently
serves these exact fields or establish canonical product identity.
"""


def test_deloox_real_product_extraction_from_jsonld_fixture():
    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml",
      "brand": {"@type": "Brand", "name": "Giorgio Armani"},
      "image": "https://cdn.example.test/profondo-125.jpg",
      "gtin13": "3614272865235",
      "sku": "DELOOX-SKU-125",
      "offers": {
        "@type": "Offer",
        "price": "96.99",
        "priceCurrency": "EUR",
        "availability": "https://schema.org/InStock"
      }
    }
    </script></head><body>
    <h1>Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml</h1>
    <div class="availability">In stock</div></body></html>
    """
    result = deloox._product(
        "https://www.deloox.nl/en/product/123/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-125-ml",
        html,
        "Giorgio Armani Acqua di Gio Profondo Eau de Parfum",
    )

    assert result is not None
    assert result["name"] == "Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml"
    assert result["source"]["source_brand"] == "Giorgio Armani"
    assert result["attributes"]["size_ml"]["value"] == 125
    assert result["attributes"]["concentration"]["value"] == "Eau de Parfum"
    assert result["offer"]["price"] == 96.99
    assert result["offer"]["availability"] == "in_stock"
    assert result["identity"]["gtin"]["value"] == "3614272865235"
    assert result["source"]["image"].endswith("profondo-125.jpg")


def test_deloox_rejects_page_without_public_price():
    # A product title includes "125 ml", but that is not a public price.
    html = """
    <html><body>
    <h1>Acqua di Gio Profondo Eau de Parfum 125 ml</h1>
    <p>Fragrance description only; no currency or offer data.</p>
    </body></html>
    """
    assert deloox._product(
        "https://www.deloox.nl/en/product/123/acqua-di-gio-profondo-eau-de-parfum-125-ml",
        html,
        "Acqua di Gio Profondo Eau de Parfum",
    ) is None


def test_parfumzentrum_real_product_extraction_from_jsonld_fixture():
    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml",
      "brand": {"@type": "Brand", "name": "Giorgio Armani"},
      "image": "https://cdn.example.test/profondo-125.jpg",
      "gtin13": "3614272865235",
      "mpn": "LB304201",
      "sku": "PZ-SKU-125",
      "productID": "PZ-PRODUCT-125",
      "offers": {
        "@type": "Offer",
        "price": "104.90",
        "priceCurrency": "EUR",
        "availability": "https://schema.org/InStock"
      }
    }
    </script></head><body>
    <h1>Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml</h1>
    <div class="product-price">104,90 €</div>
    <div class="availability">Sofort lieferbar</div>
    </body></html>
    """
    result = parfumzentrum._extract_product(
        "https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-edp-125-ml_z12345",
        "Giorgio Armani Acqua di Gio Profondo Eau de Parfum",
        html=html,
    )

    assert result is not None
    assert result["name"] == "Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml"
    assert result["brand"] == "Giorgio Armani"
    assert result["size_ml"] == 125
    assert result["concentration"] == "Eau de Parfum"
    assert result["price_num"] == 104.90
    assert result["availability"] == "in_stock"
    assert result["gtin"] == "3614272865235"
    assert result["mpn"] == "LB304201"
    assert result["sku"] == "PZ-SKU-125"
    assert result["store_product_id"] == "PZ-PRODUCT-125"
    assert result["image"].endswith("profondo-125.jpg")


def test_parfumzentrum_html_without_price_or_stock_is_not_claimed_as_offer():
    html = """
    <html><body>
    <h1>Acqua di Gio Profondo Eau de Parfum 125 ml</h1>
    <p>Fragrance description only.</p>
    </body></html>
    """
    assert parfumzentrum._extract_product(
        "https://www.parfum-zentrum.de/acqua-di-gio-profondo-edp-125-ml_z12345",
        "Acqua di Gio Profondo Eau de Parfum",
        html=html,
    ) is None


def test_deloox_extract_product_page_reuses_real_supplied_fixture():
    html = """
    <html><head><script type="application/ld+json">
    {
      "@context":"https://schema.org",
      "@type":"Product",
      "name":"Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml",
      "brand":{"@type":"Brand","name":"Giorgio Armani"},
      "image":"https://cdn.example.test/profondo-125.jpg",
      "gtin13":"3614272865235",
      "offers":{"@type":"Offer","price":"96.99","priceCurrency":"EUR","availability":"https://schema.org/InStock"}
    }
    </script></head><body>
    <h1>Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml</h1>
    </body></html>
    """
    class Response:
        status_code = 200
        url = "https://www.deloox.nl/en/product/123/giorgio-armani-acqua-di-gio-profondo-eau-de-parfum-125-ml"
        text = html
        def close(self):
            pass
    class Session:
        def __init__(self):
            self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(url)
            return Response()
    session = Session()
    result = deloox.extract_product_page(
        session,
        Response.url,
        query="Acqua di Gio Profondo Eau de Parfum",
        html=html,
    )
    assert result is not None
    assert result["attributes"]["size_ml"]["value"] == 125
    assert result["offer"]["price"] == 96.99
    assert session.calls == []


def test_parfumzentrum_page_adapter_runs_real_extraction_without_refetch():
    html = """
    <html><head><script type="application/ld+json">
    {
      "@context":"https://schema.org",
      "@type":"Product",
      "name":"Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml",
      "brand":{"@type":"Brand","name":"Giorgio Armani"},
      "image":"https://cdn.example.test/profondo-125.jpg",
      "gtin13":"3614272865235",
      "offers":{"@type":"Offer","price":"104.90","priceCurrency":"EUR","availability":"https://schema.org/InStock"}
    }
    </script></head><body>
    <h1>Giorgio Armani Acqua di Gio Profondo Eau de Parfum 125 ml</h1>
    <div class="product-price">104,90 €</div>
    <div class="availability">Sofort lieferbar</div>
    </body></html>
    """
    class Session:
        def __init__(self):
            self.calls = []
        def get(self, url, **kwargs):
            self.calls.append(url)
            raise AssertionError("HTML was supplied; a second fetch is not allowed")
    session = Session()
    result = parfumzentrum.extract_product_page(
        session,
        "https://www.parfum-zentrum.de/giorgio-armani-acqua-di-gio-profondo-edp-125-ml_z12345",
        "Giorgio Armani Acqua di Gio Profondo Eau de Parfum",
        html=html,
    )
    assert result is not None
    assert result["size_ml"] == 125
    assert result["price_num"] == 104.90
    assert session.calls == []


def test_deloox_accent_normalization_and_url_size():
    url = "https://www.deloox.be/produit/1321602/armani-acqua-di-gio-profondo-eau-de-parfum-30-ml.html"
    html = """<html><head><script type="application/ld+json">{"@type":"Product","name":"Armani Acqua Di Giò Profondo Eau de Parfum 30 ml","brand":{"@type":"Brand","name":"Armani"},"gtin13":"3614273953863","offers":{"@type":"Offer","price":"60.59","priceCurrency":"EUR","availability":"https://schema.org/InStock"}}</script></head><body><h1>Armani Acqua Di Giò Profondo Eau de Parfum 30 ml</h1></body></html>"""
    result = deloox._product(url, html, "Acqua di Gio Profondo")
    assert result is not None
    assert result["attributes"]["size_ml"]["value"] == 30
    assert result["offer"]["price"] == 60.59
    assert result["identity"]["gtin"]["value"] == "3614273953863"


def test_parfumzentrum_strips_internal_product_sku_from_query():
    html = """
    <html><head>
    <script type="application/ld+json">
    {
      "@type": "Product",
      "name": "Afnan 9 PM Eau de Parfum 100 ml",
      "brand": {"@type": "Brand", "name": "Afnan"},
      "offers": {
        "@type": "Offer",
        "price": "29.90",
        "priceCurrency": "EUR",
        "availability": "https://schema.org/InStock"
      }
    }
    </script></head><body>
    <h1>Afnan 9 PM Eau de Parfum 100 ml</h1>
    </body></html>
    """
    result = parfumzentrum._extract_product(
        "https://www.parfum-zentrum.de/afnan-9-pm-edp-100-ml_z12345",
        "Afnan 9 PM Eau de Parfum 100 ml _z12345",
        html=html,
    )
    assert result is not None
    assert result["size_ml"] == 100
    assert result["price_num"] == 29.90
