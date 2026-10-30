from bs4 import BeautifulSoup

from backend.scrapers.parfumzentrum.scraper import _semantic_price


def test_parfumzentrum_rejects_two_equally_ranked_product_prices():
    soup = BeautifulSoup(
        """
        <main>
          <h1>Liquid Brun Extrait 100 ml</h1>
          <div class="product-price">42,89 €</div>
          <div class="product-price">39,99 €</div>
        </main>
        """,
        "lxml",
    )
    assert _semantic_price(soup) is None


def test_parfumzentrum_prefers_explicit_current_price_marker():
    soup = BeautifulSoup(
        """
        <main>
          <h1>Liquid Brun Extrait 100 ml</h1>
          <div class="product-price">49,99 €</div>
          <div class="product-price-current">42,89 €</div>
        </main>
        """,
        "lxml",
    )
    assert _semantic_price(soup) == 42.89
