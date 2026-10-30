from bs4 import BeautifulSoup

from backend.scrapers.easycosmetic.scraper import _extract_selected_variant_price


def test_easycosmetic_prefers_explicit_current_price_over_regular_price():
    soup = BeautifulSoup(
        """
        <main class="product-detail">
          <h1>Liquid Brun Extrait 100 ml</h1>
          <span class="product-price-old">59,99 €</span>
          <span class="product-price-current">42,89 €</span>
        </main>
        """,
        "lxml",
    )
    assert _extract_selected_variant_price(soup) == 42.89


def test_easycosmetic_rejects_multiple_equally_scoped_prices():
    soup = BeautifulSoup(
        """
        <main class="product-detail">
          <h1>Liquid Brun Extrait 100 ml</h1>
          <span class="product-price">42,89 €</span>
          <span class="product-price">49,99 €</span>
        </main>
        """,
        "lxml",
    )
    assert _extract_selected_variant_price(soup) is None


def test_easycosmetic_ignores_unrelated_prices_outside_product_scope():
    soup = BeautifulSoup(
        """
        <main class="product-detail">
          <h1>Liquid Brun Extrait 100 ml</h1>
        </main>
        <aside>Recommended perfume 19,99 €</aside>
        """,
        "lxml",
    )
    assert _extract_selected_variant_price(soup) is None
