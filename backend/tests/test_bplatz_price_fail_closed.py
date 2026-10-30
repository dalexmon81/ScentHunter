from backend.scrapers.bplatz import scraper


class _Response:
    status_code = 200
    url = "https://en.bplatz.de/liquid-brun-extrait-100-ml"

    def __init__(self, text):
        self.text = text

    def close(self):
        pass


class _Session:
    def __init__(self, text):
        self.response = _Response(text)

    def get(self, *args, **kwargs):
        return self.response


def test_bplatz_does_not_take_unrelated_page_wide_euro_amount_as_price():
    html = """
    <html><body>
      <nav>Special offers from €19.99</nav>
      <main class="product-detail">
        <h1>Liquid Brun Extrait de Parfum 100 ml</h1>
        <p>Free delivery from €50.00</p>
      </main>
      <aside>Recommended perfume €12.99</aside>
    </body></html>
    """
    result = scraper.product_from_page(_Session(html), _Response.url, "Liquid Brun")
    assert result is not None
    assert result["price_num"] is None
