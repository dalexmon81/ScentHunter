from bs4 import BeautifulSoup

from backend.scrapers.sabina.scraper import extract_price_from_html


def test_visible_sabina_variant_price_beats_stale_meta_price():
    soup = BeautifulSoup(
        """
        <html><head><meta itemprop="price" content="59.99"></head>
        <body><main class="product-detail">
          <h1>Liquid Brun Extrait 100 ml</h1>
          <span class="current-price">42,89 €</span>
        </main></body></html>
        """,
        "lxml",
    )
    price, source = extract_price_from_html(soup)
    assert price == 42.89
    assert source == "sabina_html_price"


def test_sabina_metadata_is_only_a_fallback_when_visible_price_is_missing():
    soup = BeautifulSoup(
        '<meta itemprop="price" content="42.89"><main><h1>Product</h1></main>',
        "lxml",
    )
    price, source = extract_price_from_html(soup)
    assert price == 42.89
    assert source == "sabina_html_price_metadata_fallback"
